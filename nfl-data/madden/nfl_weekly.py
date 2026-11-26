#!/usr/bin/env python3
# NFL team grades, v4 (Nov 25 2026): nfelo team rating + nfelo game context + rest + Madden-weighted injury adjustment,
#   plus an over/under model (scoring ratings, QBs, roof, wind, cold, injuries) and home field numbers.
# Usage: nfl_weekly.py WORKDIR
#   optional in WORKDIR: lines.txt "away|home|home_spread", nfl_bet_log.csv,
#   madden_update.txt (this week's EA ratings change string, see MADDEN UPDATE below),
#   madden_launch.csv / madden_current.csv (otherwise downloaded from the prop-card repo)
# Writes nfl_grades.csv, nfl_bets.csv, nfl_bet_log.csv, nfl_inputs.csv, nfl_seasons.csv, nfl_tiers.csv, nfl_summary.csv,
#   nfl_injury_detail.csv (this week's players behind each team's injury number), madden_current.csv, madden_status.txt,
#   nfl_totals.csv (this week's over/unders), nfl_total_tiers.csv + nfl_total_summary.csv (totals backtest),
#   nfl_hfa.csv + nfl_hfa_seasons.csv (home field), nfl_model.json (this week's games for the Line Shop)
import sys,os,subprocess,datetime,glob,collections,re,unicodedata,json
import pandas as pd,numpy as np
from sklearn.linear_model import Ridge
os.chdir(sys.argv[1]);TODAY=datetime.date.today().isoformat()
FLAT=os.environ.get('NFL_FLAT')=='1'   # test switch: FLAT=1 reproduces the v2 model (every starter counts the same)
def get(url,f,check=True):
    r=subprocess.run(['curl','-sSfL','-o',f,url]);
    if check and r.returncode:raise SystemExit('download failed '+url)
    return r.returncode==0
get('https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv','games.csv')
NFR='https://raw.githubusercontent.com/greerreNFL/nfelo/main/output_data/'
get(NFR+'nfelo_games.csv','nfelo_games.csv');get(NFR+'elo_snapshot.csv','elo_snapshot.csv')
SEASON=int(pd.read_csv('games.csv',usecols=['season']).season.max())
FR={'STL':'LA','SD':'LAC','OAK':'LV','LAR':'LA','JAC':'JAX','ARZ':'ARI','BLT':'BAL','CLV':'CLE','HST':'HOU','SL':'LA'}

# ---- Injury adjustment ----
# Each player's typical snap share, minus how much of him the recent results already contain (12-week half-life),
# times his chance to play from the injury report and roster status, times his Madden weight. Summed per team.
os.makedirs('inj',exist_ok=True)
BU='https://github.com/nflverse/nflverse-data/releases/download'
for y_ in range(2013,SEASON+1):
    for k_,u_ in (('sc',f'snap_counts/snap_counts_{y_}.parquet'),('in',f'injuries/injuries_{y_}.parquet'),('rw',f'weekly_rosters/roster_weekly_{y_}.parquet')):
        f_=f'inj/{k_}_{y_}.parquet'
        if y_==SEASON or not os.path.exists(f_):
            if not get(f'{BU}/{u_}',f_,check=False):print('missing',u_)
get(f'{BU}/players/players.parquet','inj/players.parquet')
plall=pd.read_parquet('inj/players.parquet')

# ---- Madden ratings ----
# madden_launch.csv: season,pfr,ovr = each season's launch rating (season = NFL season). Used for every past game, so the
#   backtest never sees a rating from later than the game.
# madden_current.csv: ea_id,name,pos,birthdate,ovr,iteration = EA's latest in-season ratings. Used only for the upcoming week.
# A player counts as max(rating - 62, 0), scaled so the average regular starter = 1. Unrated players count as a 64.
MR='https://raw.githubusercontent.com/aatrain23/prop-card/main/nfl-data/madden/'
MBASE,MUNR=62.,64.
for f_,u_ in (('madden_launch.csv','launch.csv'),('madden_current.csv','current.csv')):
    if not os.path.exists(f_):get(MR+u_,f_)
def nm(s):
    s=unicodedata.normalize('NFKD',str(s)).encode('ascii','ignore').decode().lower()
    s=re.sub(r"[.'`,-]",'',s);s=re.sub(r'\b(jr|sr|ii|iii|iv|v)\b','',s);return re.sub(r'\s+',' ',s).strip()
# MADDEN UPDATE: madden_update.txt holds one string made in the browser on EA's ratings page:
#   NEWITER|BASEITER|n|sum|ck#id:ovr,id:ovr,...#id|name|pos|yyyy-mm-dd;...#id,id,...
#   = ratings that changed since BASEITER, players new since BASEITER, players no longer listed. n, sum and ck describe the
#   full new list (count, sum of ratings, sum of id*rating mod 1000000007); the update is applied only if all three match.
def madden_update():
    cur=pd.read_csv('madden_current.csv',dtype={'birthdate':str});st='no update file: using saved ratings ('+str(cur.iteration.iloc[0])+')'
    if os.path.exists('madden_update.txt'):
        try:
            raw=open('madden_update.txt').read().strip();p=raw.split('#')
            if raw.startswith('SAME'):st='EA has no newer ratings than the saved ones ('+str(cur.iteration.iloc[0])+')'
            else:
                h=p[0].split('|');new,base,n,sm,ck=h[0],h[1],int(h[2]),int(h[3]),int(h[4])
                if base!=str(cur.iteration.iloc[0]):raise ValueError(f'update is against {base} but saved ratings are {cur.iteration.iloc[0]}')
                c=cur.set_index('ea_id')
                if len(p)>3 and p[3].strip():c=c.drop([int(i) for i in p[3].split(',') if i.strip()])
                if len(p)>2 and p[2].strip():
                    for t in p[2].split(';'):
                        a=t.split('|')
                        if len(a)>=4:c.loc[int(a[0]),['name','pos','birthdate']]=[a[1],a[2],a[3]]
                if len(p)>1 and p[1].strip():
                    for t in p[1].split(','):
                        i,o=t.split(':');c.loc[int(i),'ovr']=int(o)
                c['ovr']=c.ovr.astype(int);c['iteration']=new;c=c.reset_index()
                got=(len(c),int(c.ovr.sum()),int(sum(int(i)*int(o) for i,o in zip(c.ea_id,c.ovr))%1000000007))
                if got!=(n,sm,ck):raise ValueError(f'check failed: got {got}, EA says {(n,sm,ck)}')
                if c.name.isna().any():raise ValueError('new player without a name')
                cur=c[['ea_id','name','pos','birthdate','ovr','iteration']];st=f'updated to {new} from {base}: {len(cur)} players, check passed'
        except Exception as e:st='MADDEN UPDATE FAILED ('+str(e)+'): using saved ratings ('+str(cur.iteration.iloc[0])+')'
    cur[['ea_id','name','pos','birthdate','ovr','iteration']].to_csv('madden_current.csv',index=False)
    open('madden_status.txt','w').write(st+'\n');print('Madden:',st);return cur
MC=madden_update()
pm=plall.dropna(subset=['pfr_id']).copy();pm['n']=pm.display_name.map(nm);pm['bd']=pd.to_datetime(pm.birth_date,errors='coerce').dt.strftime('%Y-%m-%d').fillna('')
pm['ln']=pm.n.str.split().str[-1]
k1=dict(zip(pm.n+'|'+pm.bd,pm.pfr_id));u2=pm[pm.bd!=''].drop_duplicates(['ln','bd'],keep=False);k2=dict(zip(u2.ln+'|'+u2.bd,u2.pfr_id))
u3=pm[pm.last_season.fillna(0)>=SEASON-1].drop_duplicates('n',keep=False);k3=dict(zip(u3.n,u3.pfr_id))
pm['il']=pm.n.str[:1]+' '+pm.ln;u4=pm[pm.last_season.fillna(0)>=SEASON-1].drop_duplicates('il',keep=False);k4=dict(zip(u4.il,u4.pfr_id))   # Zach / Zachary
def topfr(name,bd):
    n=nm(name);bd=bd if isinstance(bd,str) else ''
    if not n:return None
    return k1.get(n+'|'+bd) or (k2.get(n.split()[-1]+'|'+bd) if bd else None) or k3.get(n) or k4.get(n[:1]+' '+n.split()[-1])
MC['pfr']=[topfr(a,b) for a,b in zip(MC.name,MC.birthdate)]
MCUR={r.pfr:float(r.ovr) for r in MC.dropna(subset=['pfr']).itertuples()}
ML=pd.read_csv('madden_launch.csv');MD={(int(r.season),r.pfr):float(r.ovr) for r in ML.itertuples()}
def ovr_launch(s,pid):
    v=MD.get((s,pid))
    if v is None:v=MD.get((s-1,pid))
    return MUNR if v is None else v

OFF={'T':'OL','G':'OL','C':'OL','OL':'OL','OT':'OL','OG':'OL','WR':'WR','TE':'TE','RB':'RB','FB':'RB','HB':'RB'}
DEF={'DE':'DL','DT':'DL','NT':'DL','DL':'DL','OLB':'EDGE','LB':'LB','ILB':'LB','MLB':'LB','CB':'CB','DB':'CB','S':'S','FS':'S','SS':'S','SAF':'S'}
sc=pd.concat([pd.read_parquet(f) for f in sorted(glob.glob('inj/sc_*.parquet'))]);sc['team']=sc.team.replace(FR)
sc=sc[sc.position.isin(list(OFF)+list(DEF))]
sc['grp']=sc.position.map(OFF).fillna(sc.position.map(DEF));sc['side']=np.where(sc.position.isin(list(OFF)),'o','d')
sc['pct']=np.where(sc.side=='o',sc.offense_pct,sc.defense_pct).astype(float)
pl=plall[['gsis_id','pfr_id']].dropna();g2p=dict(zip(pl.gsis_id,pl.pfr_id))
ij=pd.concat([pd.read_parquet(f) for f in sorted(glob.glob('inj/in_*.parquet'))]);ij['team']=ij.team.replace(FR);ij['pfr']=ij.gsis_id.map(g2p)
ST={(r.season,r.week,r.team,r.pfr):r.report_status for r in ij.dropna(subset=['pfr']).itertuples()}
rw=pd.concat([pd.read_parquet(f,columns=['season','week','team','pfr_id','gsis_id','status']) for f in sorted(glob.glob('inj/rw_*.parquet'))]);rw['pfr_id']=rw.pfr_id.fillna(rw.gsis_id.map(g2p));rw=rw.dropna(subset=['pfr_id']);rw['team']=rw.team.replace(FR)
RS={(r.season,r.week,r.team,r.pfr_id):r.status for r in rw.itertuples()}
g=pd.read_csv('games.csv');g=g[g.season>=2013].copy()
for c in['home_team','away_team']:g[c]=g[c].replace(FR)
g['date']=pd.to_datetime(g.gameday);g=g.sort_values(['date','game_id'])
_nx=g[g.result.isna()&(g.season==SEASON)];UPC=set(_nx[_nx.week==_nx.week.min()].game_id) if len(_nx) else set()   # the upcoming week's games
dt=dict(zip(g.game_id,g.date));sc['date']=sc.game_id.map(dt);sc=sc.dropna(subset=['date'])
tgl=collections.defaultdict(list)
for r in g.itertuples():
    tgl[r.home_team].append((r.date,r.game_id,r.season,r.week));tgl[r.away_team].append((r.date,r.game_id,r.season,r.week))
snap={(r.game_id,r.team):{} for r in sc[['game_id','team']].drop_duplicates().itertuples()};pinfo={}
for r in sc.itertuples():snap[(r.game_id,r.team)][r.pfr_player_id]=r.pct;pinfo[r.pfr_player_id]=r.grp
OUTS={'RES','PUP','CUT','SUS','DEV','RET','NWT','EXE','TRD','TRC','TRT','RSN','NON','UDF','UFA'}
def key(s,w,t,pid,inlast):
    rs=RS.get((s,w,t,pid));st=ST.get((s,w,t,pid))
    if rs in OUTS:return ('roster_out',False)
    if st in('Out','Doubtful'):return ('out',False)
    a_='L' if inlast else 'N'
    if st=='Questionable':return ('q'+a_,rs=='INA')
    if (s,w,t,pid) in ST:return ('listed'+a_,rs=='INA')
    return ('none'+a_,rs=='INA')
PR={'roster_out':0.,'out':0.,'qL':.75,'qN':.53,'listedL':.97,'listedN':.77,'noneL':.93,'noneN':.03}
# Hand-set statuses (Nov 25 2026, Aidan: "update it to Parsons confirmed playing"): status_overrides.csv, columns
# season,week,team,player,chance_to_play,note. A row replaces the player's chance to play for that one game
# (1 = confirmed playing, 0 = confirmed out); the injury detail then shows his status as 'confirmed' or 'ruled_out'.
OV={}
if os.path.exists('status_overrides.csv'):
    _n2p={nm(r.display_name):r.pfr_id for r in plall.dropna(subset=['pfr_id']).itertuples()}
    for r in pd.read_csv('status_overrides.csv').itertuples():
        _p=_n2p.get(nm(str(r.player)))
        if _p is None:print('status override: player not found:',r.player);continue
        OV[(int(r.season),int(r.week),FR.get(r.team,r.team),_p)]=min(1.,max(0.,float(r.chance_to_play)))
    print('status overrides:',len(OV))
prow=[]
for t,L in tgl.items():
    L=sorted(L)
    for k,(d0,gid,s,w) in enumerate(L):
        past=[x for x in L[:k] if (d0-x[0]).days<=1100 and (x[1],t) in snap]
        wts=np.array([.5**((d0-x[0]).days/7/12) for x in past]);W=wts.sum() if len(past) else 0
        hist=collections.defaultdict(list)
        for i,x in enumerate(past):
            for pid,pc in snap[(x[1],t)].items():hist[pid].append((i,pc))
        last=snap[(past[-1][1],t)] if past else {}
        prow.append((gid,t,s,None,None,0.,0.,0.,0.,'',MUNR,MUNR))   # keeps every team-game in the table
        for pid,h in hist.items():
            baked=sum(wts[i]*pc for i,pc in h)/W
            played=[pc for i,pc in h if pc>0.05][-4:]
            c=np.mean(played) if played else 0
            if c<0.3 and baked<0.15:continue
            kk=key(s,w,t,pid,last.get(pid,0)>.05)[0];p=PR.get(kk,.5);ol=ovr_launch(s,pid)
            if (s,w,t,pid) in OV:p=OV[(s,w,t,pid)];kk='confirmed' if p>=.5 else 'ruled_out'
            ou=MCUR.get(pid,ol) if gid in UPC else ol       # latest EA rating for the upcoming week only
            prow.append((gid,t,s,pid,pinfo.get(pid),c,p,baked,c*p-baked,kk,ol,ou))
PP=pd.DataFrame(prow,columns=['game_id','team','season','pid','grp','c','p','baked','contrib','status','ovr_launch','ovr'])
_st=(PP.c>=0.5)&(PP.season>=2015)&PP.pid.notna()
MNORM=float((PP.ovr_launch[_st]-MBASE).clip(lower=0).mean())      # average regular starter's rating above 62
PP['w']=1. if FLAT else (PP.ovr-MBASE).clip(lower=0)/MNORM
PP['pts']=PP.contrib*PP.w
IJ=PP.groupby(['game_id','team']).pts.sum()
print('Madden: average starter weight base %.2f (rating %.1f = 1.0); upcoming-week players with a current EA rating: %d of %d'%(MNORM,MBASE+MNORM,int(PP[PP.game_id.isin(UPC)&PP.pid.notna()].pid.isin(MCUR).sum()),int((PP.game_id.isin(UPC)&PP.pid.notna()).sum())))

# ---- Game table with nfelo inputs ----
a=pd.read_csv('games.csv');a=a[a.season>=2015].copy()
for c in['home_team','away_team']:a[c]=a[c].replace(FR)
a['date']=pd.to_datetime(a.gameday);a=a.sort_values(['date','game_id']).reset_index(drop=True)
def norm(x):
    p=x.split('_');p[2]=FR.get(p[2],p[2]);p[3]=FR.get(p[3],p[3]);return '_'.join(p)
a['gk']=a.game_id.map(norm)
n=pd.read_csv('nfelo_games.csv');n['gk']=n.game_id.map(norm)
n['d_nf']=((n.starting_nfelo_home+n.home_538_qb_adj)-(n.starting_nfelo_away+n.away_538_qb_adj))/25
n['ctx']=(n.hfa_mod+n.home_net_bye_mod+n.div_game_mod+n.dif_surface_mod+n.home_time_advantage_mod)/25
a=a.merge(n[['gk','d_nf','ctx']],on='gk',how='left')
a['inj_h']=[IJ.get((i,h),np.nan) for i,h in zip(a.game_id,a.home_team)];a['inj_a']=[IJ.get((i,w),np.nan) for i,w in zip(a.game_id,a.away_team)]
a['d_inj']=a.inj_h-a.inj_a;a['d_rest']=(a.home_rest-a.away_rest).clip(-7,7)
C=['d_nf','ctx','d_rest','d_inj'];CN=['d_nf','ctx','d_rest']

# ---- Over/under inputs ----
# Scoring ratings: each team's offense and defense in points vs league average, updated after every game (4% of the miss),
# pulled 40% back to average each new season; the league scoring level moves 1% of each miss. Nothing from the betting market.
TK,TR,TM=.04,.6,.01
def scoring_ratings():
    off=collections.defaultdict(float);de=collections.defaultdict(float);mu=45.;ls=None;out={}
    for x in g.itertuples():
        if x.season!=ls:
            for t in list(off):off[t]*=TR;de[t]*=TR
            ls=x.season
        ph=mu/2+off[x.home_team]-de[x.away_team];pa=mu/2+off[x.away_team]-de[x.home_team];out[x.game_id]=ph+pa
        if pd.notna(x.home_score) and pd.notna(x.away_score):
            eh=x.home_score-ph;ea=x.away_score-pa
            off[x.home_team]+=TK*eh;de[x.away_team]-=TK*eh;off[x.away_team]+=TK*ea;de[x.home_team]-=TK*ea;mu+=TM*(eh+ea)
    return out,off,de,mu
_tr,TOFF,TDEF,TMU=scoring_ratings()
a['t_rate']=a.game_id.map(_tr);a['qb_sum']=a.gk.map(n.drop_duplicates('gk').set_index('gk').eval('(home_538_qb_adj+away_538_qb_adj)/25'))
# Stadiums (lat, lon) for the forecast; retractable roofs count as closed until the league says otherwise
STAD={'ARI':(33.5276,-112.2626),'ATL':(33.7554,-84.4008),'BAL':(39.2780,-76.6227),'BUF':(42.7738,-78.7870),'CAR':(35.2258,-80.8528),'CHI':(41.8623,-87.6167),
 'CIN':(39.0954,-84.5160),'CLE':(41.5061,-81.6995),'DAL':(32.7473,-97.0945),'DEN':(39.7439,-105.0201),'DET':(42.3400,-83.0456),'GB':(44.5013,-88.0622),
 'HOU':(29.6847,-95.4107),'IND':(39.7601,-86.1639),'JAX':(30.3239,-81.6373),'KC':(39.0489,-94.4839),'LA':(33.9535,-118.3392),'LAC':(33.9535,-118.3392),
 'LV':(36.0909,-115.1833),'MIA':(25.9580,-80.2389),'MIN':(44.9736,-93.2575),'NE':(42.0909,-71.2643),'NO':(29.9511,-90.0812),'NYG':(40.8135,-74.0745),
 'NYJ':(40.8135,-74.0745),'PHI':(39.9008,-75.1675),'PIT':(40.4468,-80.0158),'SEA':(47.5952,-122.3316),'SF':(37.4033,-121.9694),'TB':(27.9759,-82.5033),
 'TEN':(36.1665,-86.7713),'WAS':(38.9076,-76.8645)}
RETRACT={'ARI','ATL','DAL','HOU','IND'}
a['indoor']=(a.roof.isin(['dome','closed'])|(a.roof.isna()&a.home_team.isin(RETRACT|{'DET','LA','LAC','LV','MIN','NO'}))).astype(float)
# Forecast for the upcoming week's outdoor games (Open-Meteo, wind in mph and temperature in F at kickoff). No forecast = a calm, mild day.
WX={}
def forecast(r):
    try:
        la,lo=STAD[r.home_team];f=f'wx_{r.game_id}.json'
        u=f'https://api.open-meteo.com/v1/forecast?latitude={la}&longitude={lo}&hourly=temperature_2m,wind_speed_10m&wind_speed_unit=mph&temperature_unit=fahrenheit&timezone=America%2FNew_York&start_date={r.gameday}&end_date={r.gameday}'
        if subprocess.run(['curl','-sSfL','--max-time','20','-o',f,u],capture_output=True).returncode:return None
        h=json.load(open(f))['hourly'];hh=int(str(r.gametime)[:2])+1;i=[t[11:13] for t in h['time']].index('%02d'%min(hh,23))   # an hour into the game
        return float(h['temperature_2m'][i]),float(h['wind_speed_10m'][i])
    except Exception:return None
for r in a[a.game_id.isin(UPC)].itertuples():
    if r.indoor==0 and r.location!='Neutral' and pd.isna(r.wind):
        w_=forecast(r)
        if w_:WX[r.game_id]=w_
a['temp_u']=[WX[i][0] if i in WX else t for i,t in zip(a.game_id,a.temp)];# A forecast is not the wind the game ends up with: over 363 outdoor games in 2024-25, Open-Meteo's wind at the stadium averaged 7.5 mph
# against 8.0 recorded, and each mph of it was worth 0.72 mph of recorded wind. So a forecast counts as 8.0 + 0.72 x (forecast - 7.5).
WXW=lambda f:8.0+0.72*(f-7.5)
a['wind_u']=[WXW(WX[i][1]) if i in WX else w for i,w in zip(a.game_id,a.wind)]
a['windx']=np.where(a.indoor==1,0,(a.wind_u.fillna(8).clip(0,30)-10).clip(lower=0))     # mph of wind past 10
a['cold']=np.where(a.indoor==1,0,(40-a.temp_u.fillna(60)).clip(lower=0))                # degrees below 40
_o=PP[PP.pid.notna()&PP.grp.isin(['OL','WR','TE','RB'])].groupby('game_id').pts.sum();_d=PP[PP.pid.notna()&~PP.grp.isin(['OL','WR','TE','RB'])].groupby('game_id').pts.sum()
a['inj_off']=a.game_id.map(_o).fillna(0);a['inj_def']=a.game_id.map(_d).fillna(0)     # both teams' offense / defense injury numbers
CT=['t_rate','qb_sum','indoor','windx','cold','inj_off','inj_def']
ok=a.result.notna()&a.d_nf.notna()&a.d_inj.notna()
# ---- Walk-forward backtest: each season fit only on earlier seasons (2015 on) ----
d=a[ok&a.spread_line.notna()].copy();bt=[]
for S in range(2016,SEASON+1):
    tr=d[d.season<S];te=d[d.season==S].copy()
    if te.empty:continue
    te['p']=Ridge(alpha=30).fit(tr[C],tr.result).predict(te[C]);te['pn']=Ridge(alpha=30).fit(tr[CN],tr.result).predict(te[CN]);bt.append(te)
bt=pd.concat(bt)
def cov(p,x):
    gap=p-x.spread_line;return gap,np.where(gap>0,x.result-x.spread_line,x.spread_line-x.result)
bt['gap'],bt['cov']=cov(bt.p,bt);bt['gapn'],bt['covn']=cov(bt.pn,bt)
def rec(m,col='cov'):
    x=bt.loc[m,col];w=int((x>0).sum());l=int((x<0).sum());return w,l
S_=[]
for s_,x in bt.groupby('season'):
    w,l=rec((bt.season==s_)&(bt.gap.abs()>=3))
    S_.append(dict(season=s_,games=len(x),model_miss=round((x.p-x.result).abs().mean(),2),no_injury_miss=round((x.pn-x.result).abs().mean(),2),
      market_miss=round((x.spread_line-x.result).abs().mean(),2),ab_record=f'{w}-{l}',ab_cover=round(100*w/max(w+l,1),1)))
pd.DataFrame(S_).to_csv('nfl_seasons.csv',index=False)
T=[];TI=[('A','5+',5,99),('B','3 to 5',3,5),('C','1.5 to 3',1.5,3),('D','Under 1.5',0,1.5)]
for gr,lab,lo,hi in TI:
    m=(bt.gap.abs()>=lo)&(bt.gap.abs()<hi);w,l=rec(m);w2,l2=rec(m&(bt.season>=2024))
    mn=(bt.gapn.abs()>=lo)&(bt.gapn.abs()<hi);w3,l3=rec(mn,'covn')
    T.append(dict(grade=gr,gap=lab,record=f'{w}-{l}',cover=round(100*w/max(w+l,1),1),roi=round(100*(w*100/110-l)/max(w+l,1),1),
      recent_record=f'{w2}-{l2}',recent_cover=round(100*w2/max(w2+l2,1),1),no_injury_record=f'{w3}-{l3}'))
pd.DataFrame(T).to_csv('nfl_tiers.csv',index=False)

# ---- Over/under backtest: each season fit only on earlier seasons, against the closing total ----
okt=a.total.notna()&a.total_line.notna()&a.t_rate.notna()&a.qb_sum.notna()
dt_=a[okt].copy();tb=[]
for S in range(2017,SEASON+1):
    tr=dt_[dt_.season<S];te=dt_[dt_.season==S].copy()
    if te.empty:continue
    te['p']=Ridge(alpha=30).fit(tr[CT],tr.total).predict(te[CT]);tb.append(te)
tb=pd.concat(tb);tb['gap']=tb.p-tb.total_line;tb['cov']=np.where(tb.gap>0,tb.total-tb.total_line,tb.total_line-tb.total)
def trec(m):
    x=tb.loc[m,'cov'];return int((x>0).sum()),int((x<0).sum())
TT=[]
for gr,lab,lo,hi in TI:
    m=(tb.gap.abs()>=lo)&(tb.gap.abs()<hi);w,l=trec(m);w2,l2=trec(m&(tb.season>=2024));wo,lo_=trec(m&(tb.gap>0));wu,lu=trec(m&(tb.gap<0))
    TT.append(dict(grade=gr,gap=lab,record=f'{w}-{l}',cover=round(100*w/max(w+l,1),1),roi=round(100*(w*100/110-l)/max(w+l,1),1),
      recent_record=f'{w2}-{l2}',recent_cover=round(100*w2/max(w2+l2,1),1),over_record=f'{wo}-{lo_}',under_record=f'{wu}-{lu}'))
pd.DataFrame(TT).to_csv('nfl_total_tiers.csv',index=False)
w,l=trec(tb.gap.abs()>=3)
pd.DataFrame([dict(games=len(tb),model_miss=round((tb.p-tb.total).abs().mean(),2),market_miss=round((tb.total_line-tb.total).abs().mean(),2),
  first_season=int(tb.season.min()),ab_record=f'{w}-{l}',ab_cover=round(100*w/max(w+l,1),1),ab_roi=round(100*(w*100/110-l)/max(w+l,1),1))]).to_csv('nfl_total_summary.csv',index=False)
mt=Ridge(alpha=30).fit(dt_[CT],dt_.total);cot=dict(zip(CT,mt.coef_));it0=mt.intercept_
print('totals',{k:round(v,3) for k,v in cot.items()},round(it0,2));print(pd.read_csv('nfl_total_summary.csv').to_string());print(pd.read_csv('nfl_total_tiers.csv').to_string())

# ---- Fit on all games 2015 on, then grade teams ----
tr=a[ok];m=Ridge(alpha=30).fit(tr[C],tr.result);co=dict(zip(C,m.coef_));i0=m.intercept_
nx=a[a.result.isna()&(a.season==SEASON)]
if nx.empty:raise SystemExit('No games left this season')
wk=nx.week.min();nx=nx[nx.week==wk]
sn=pd.read_csv('elo_snapshot.csv');sn['team']=sn.team.replace(FR)
sn=sn.sort_values(['season','week']).groupby('team').tail(1).set_index('team')
IW={}
for r in nx.itertuples():IW[r.home_team]=r.inj_h;IW[r.away_team]=r.inj_a
mi=np.nanmean([v for v in IW.values() if pd.notna(v)]) if IW else 0.
lastqb={}
for r in a.itertuples():
    if isinstance(r.home_qb_name,str):lastqb[r.home_team]=r.home_qb_name
    if isinstance(r.away_qb_name,str):lastqb[r.away_team]=r.away_qb_name
teams=sorted(set(a[a.season==SEASON].home_team));nfm=sn.loc[teams,'nfelo'].mean();basem=sn.loc[teams,'nfelo_base'].mean()
rows=[]
for t in teams:
    s=sn.loc[t];v=IW.get(t,mi);v=mi if pd.isna(v) else v
    rows.append(dict(team=t,qb=lastqb.get(t,''),team_rating=co['d_nf']*(s.nfelo_base-basem)/25,qb_adj=co['d_nf']*(s.qb_adj-(nfm-basem))/25,
      injuries=co['d_inj']*(v-mi),rated_week=int(s.week)))
G=pd.DataFrame(rows);G['grade']=(50+G.team_rating+G.qb_adj+G.injuries).round(1)
rr=a[(a.season==SEASON)&a.result.notna()]
def wl(t):
    h=rr[rr.home_team==t].result;w=rr[rr.away_team==t].result;ti=(h==0).sum()+(w==0).sum()
    return f"{(h>0).sum()+(w<0).sum()}-{(h<0).sum()+(w>0).sum()}"+(f"-{ti}" if ti else '')
G['record']=G.team.map(wl);G=G.sort_values('grade',ascending=False).reset_index(drop=True);G.insert(0,'rank',G.index+1)
for k in['team_rating','qb_adj','injuries']:G[k]=G[k].round(1)
G['note']=np.where(G.rated_week<wk,'Bye: nfelo rating from before last game','')
G[['rank','team','grade','record','qb','team_rating','qb_adj','injuries','note']].to_csv('nfl_grades.csv',index=False)
# this week's players behind each team's injury number (points = model points for or against the team)
nmap=plall.dropna(subset=['pfr_id']).drop_duplicates('pfr_id').set_index('pfr_id').display_name
D=PP[PP.game_id.isin(set(nx.game_id))&PP.pid.notna()].copy();D['player']=D.pid.map(nmap);D['points']=(co['d_inj']*D.pts).round(2)
D['madden']=D.ovr.round(0).astype(int);D['madden_source']=np.where(D.pid.isin(MCUR),'current','launch or unrated')
D=D[D.points.abs()>=0.1].sort_values(['team','points'])
D.assign(snap_share=D.c.round(2),chance_to_play=D.p,already_in_results=D.baked.round(2))[['team','player','grp','madden','madden_source','status','snap_share','chance_to_play','already_in_results','points']].to_csv('nfl_injury_detail.csv',index=False)
# typical home edge for the calculator: average context of home games, last 3 seasons, non-neutral
hm=a[(a.season>=SEASON-2)&(a.location!='Neutral')&a.ctx.notna()];he=i0+co['ctx']*hm.ctx.mean()
# ---- This week's games ----
LN={};LT={}
if os.path.exists('lines.txt'):
    for l in open('lines.txt'):
        if l.count('|')>=2:
            x_=l.strip().split('|');LN[(x_[0],x_[1])]=float(x_[2])
            if len(x_)>3 and x_[3].strip():LT[(x_[0],x_[1])]=float(x_[3])     # optional 4th field: the game total
B=[];TB=[]
for r in nx.itertuples():
    if pd.isna(r.d_nf):print('no nfelo row',r.game_id);continue
    di=0. if pd.isna(r.d_inj) else r.d_inj
    pr=i0+co['d_nf']*r.d_nf+co['ctx']*r.ctx+co['d_rest']*r.d_rest+co['d_inj']*di
    line=LN.get((r.away_team,r.home_team),r.spread_line);gap=pr-line if pd.notna(line) else np.nan
    side=r.home_team if gap>0 else r.away_team;sl=(-line if gap>0 else line)
    t='' if pd.isna(gap) else 'A' if abs(gap)>=5 else 'B' if abs(gap)>=3 else 'C' if abs(gap)>=1.5 else 'D'
    # over/under, each team's projected points, and the home field number inside this game's spread
    tl=LT.get((r.away_team,r.home_team),r.total_line);pt=it0+sum(cot[k]*getattr(r,k) for k in CT) if pd.notna(r.t_rate) and pd.notna(r.qb_sum) else np.nan
    tg=pt-tl if pd.notna(tl) and pd.notna(pt) else np.nan
    tt='' if pd.isna(tg) else 'A' if abs(tg)>=5 else 'B' if abs(tg)>=3 else 'C' if abs(tg)>=1.5 else 'D'
    wx='indoors' if r.indoor==1 else (f'{WX[r.game_id][0]:.0f}F, wind {WX[r.game_id][1]:.0f} mph' if r.game_id in WX else 'no forecast yet')
    TB.append(dict(week=int(wk),date=r.gameday,matchup=f"{r.away_team} @ {r.home_team}",model_total=None if pd.isna(pt) else round(pt,1),market_total=tl,
      side='' if pd.isna(tg) else 'Over' if tg>0 else 'Under',gap=None if pd.isna(tg) else round(abs(tg),1),grade=tt,
      proj_away=None if pd.isna(pt) else round((pt-pr)/2,1),proj_home=None if pd.isna(pt) else round((pt+pr)/2,1),weather=wx,
      home_field=0. if r.location=='Neutral' else round(i0+co['ctx']*r.ctx,1)))
    B.append(dict(week=int(wk),date=r.gameday,matchup=f"{r.away_team} @ {r.home_team}",model_home=round(pr,1),market_home=line,side=side,line=sl,gap=round(abs(gap),1),grade=t,home_qb=r.home_qb_name if isinstance(r.home_qb_name,str) else lastqb.get(r.home_team,''),away_qb=r.away_qb_name if isinstance(r.away_qb_name,str) else lastqb.get(r.away_team,'')))
Bd=pd.DataFrame(B);Bd=Bd[Bd.date>=TODAY].sort_values('gap',ascending=False);Bd.to_csv('nfl_bets.csv',index=False)
Td=pd.DataFrame(TB);Td=Td[Td.date>=TODAY].sort_values('gap',ascending=False);Td.to_csv('nfl_totals.csv',index=False)
# ---- Home field ----
# By season: how much better home teams did than the ratings, rest and injuries said (non-neutral games).
# By team: (home games minus road games) / 2 vs what the model expected, last 10 seasons, then pulled toward the league number
# by how much of the team-to-team spread is real rather than luck. A check on 2018 on showed team numbers add nothing to the
# spread model, so they are shown for information and are not in the grades.
hd=a[ok&(a.location!='Neutral')].copy();hd['base']=co['d_nf']*hd.d_nf+co['d_rest']*hd.d_rest+co['d_inj']*hd.d_inj
hd['res']=hd.result-(i0+hd.base+co['ctx']*hd.ctx)
pd.DataFrame([dict(season=int(s_),games=len(x),home_margin=round(x.result.mean(),2),home_edge=round((x.result-x.base).mean(),2),
  home_win_pct=round(100*((x.result>0).sum()+.5*(x.result==0).sum())/len(x),1)) for s_,x in hd.groupby('season')]).to_csv('nfl_hfa_seasons.csv',index=False)
h10=hd[hd.season>=SEASON-9];HR=[]
for t in teams:
    h_=h10[h10.home_team==t].res;w_=-h10[h10.away_team==t].res
    HR.append(dict(team=t,home_games=len(h_),delta=(h_.mean()-w_.mean())/2,se2=(h_.var()/len(h_)+w_.var()/len(w_))/4))
H=pd.DataFrame(HR);sig=max(H.delta.var()-H.se2.mean(),0.);HSH=sig/H.delta.var() if H.delta.var()>0 else 0.
hw={x['matchup'].split(' @ ')[1]:x['home_field'] for x in TB}
H['raw']=(he+H.delta).round(1);H['home_edge']=(he+HSH*H.delta).round(1);H['this_week']=H.team.map(hw)
hrec=lambda t:(lambda x:f"{int((x>0).sum())}-{int((x<0).sum())}"+(f"-{int((x==0).sum())}" if (x==0).any() else ''))(h10[h10.home_team==t].result)
H['home_record']=H.team.map(hrec)
H.sort_values('home_edge',ascending=False)[['team','home_edge','raw','home_games','home_record','this_week']].to_csv('nfl_hfa.csv',index=False)
print('home field: league %.2f, share of team differences kept %.2f'%(he,HSH));print(pd.read_csv('nfl_hfa_seasons.csv').to_string());print(pd.read_csv('nfl_hfa.csv').to_string());print(Td.to_string())
# ---- Line Shop file: this week's games, home spread (minus = home favored) and total ----
tmap={x['matchup']:x for x in TB};MJ=[]
for x in B:
    if x['date']<TODAY:continue
    y=tmap[x['matchup']];aw,hm_=x['matchup'].split(' @ ');f_=lambda v:None if v is None or pd.isna(v) else float(v)
    MJ.append(dict(away=aw,home=hm_,date=x['date'],grade=x['grade'],model_home=round(-x['model_home'],1),tue_home=None if pd.isna(x['market_home']) else -float(x['market_home']),
      model_total=f_(y['model_total']),tue_total=f_(y['market_total']),total_grade=y['grade'],proj_away=f_(y['proj_away']),proj_home=f_(y['proj_home']),
      weather=y['weather'],home_field=f_(y['home_field']),home_qb=x['home_qb'],away_qb=x['away_qb']))
json.dump(dict(label=f'Week {int(wk)} grades',week=int(wk),updated=TODAY,league_home_edge=round(he,2),games=MJ),open('nfl_model.json','w'),indent=1)
# ---- Inputs, summary ----
ex=lambda r:round((r-MBASE)/MNORM,1)
pd.DataFrame([
 dict(input='nfelo team rating',weight=round(co['d_nf'],3),note="nfelo's Elo rating for the team plus its QB adjustment, in points (Elo / 25)"),
 dict(input='Game context (nfelo)',weight=round(co['ctx'],3),note='Home field, byes, travel and time zones, surface and divisional games, from nfelo'),
 dict(input='Injuries and roster moves',weight=round(co['d_inj'],3),note=('Points per full-time starter missing, beyond what recent results already contain' if FLAT else
   f'Points per average full-time starter missing, beyond what recent results already contain. Players count by Madden rating: a {int(round(MBASE+MNORM))} counts as 1, an 88 as {ex(88)}, a 99 as {ex(99)}, a 68 as {ex(68)}')),
 dict(input='Rest difference',weight=round(co['d_rest'],3),note='Days of rest, capped at 7, per day'),
 dict(input='Typical home edge',weight=round(he,2),note='Points, average of the last three seasons')]).to_csv('nfl_inputs.csv',index=False)
w,l=rec(bt.gap.abs()>=3)
pd.DataFrame([dict(games=len(bt),model_miss=round((bt.p-bt.result).abs().mean(),2),no_injury_miss=round((bt.pn-bt.result).abs().mean(),2),
  market_miss=round((bt.spread_line-bt.result).abs().mean(),2),through=f"Week {int(rr.week.max())}, {SEASON}",home_edge=round(he,2),
  ab_record=f'{w}-{l}',ab_cover=round(100*w/(w+l),1),ab_roi=round(100*(w*100/110-l)/(w+l),1))]).to_csv('nfl_summary.csv',index=False)
print(co,round(i0,2),'home edge',round(he,2));print('model miss %.3f'%(bt.p-bt.result).abs().mean());print(pd.read_csv('nfl_summary.csv').to_string());print(pd.read_csv('nfl_tiers.csv').to_string())
print(G.to_string());print(Bd.to_string())
# ---- Bet log: grade finished games, add this week's A and B bets ----
LC=['week','matchup','side','line','grade','gap','side_margin','result','logged']
L=pd.read_csv('nfl_bet_log.csv') if os.path.exists('nfl_bet_log.csv') else pd.DataFrame(columns=LC)
fin={f"{r.away_team} @ {r.home_team}|{r.week}":r for r in rr.itertuples()}
L['side_margin']=L.side_margin.astype(object);L['result']=L.result.astype(object);L['gap']=L.gap.astype(object);L['grade']=L.grade.astype(object)
for i,r in L.iterrows():
    f=fin.get(f"{r.matchup}|{r.week}")
    if f is None:continue
    mm=f.result if r.side==f.home_team else -f.result;L.at[i,'side_margin']=mm
    v=mm+float(r.line);L.at[i,'result']='W' if v>0 else 'L' if v<0 else 'P'
# regrade this week's unplayed log entries with the current model, at the line they were logged at (Aidan, Nov 25 2026)
MH={x['matchup']:x['model_home'] for x in B}
for i,r in L.iterrows():
    if str(r.result) not in ('W','L','P') and int(r.week)==int(wk) and r.matchup in MH:
        home=r.matchup.split(' @ ')[1];hl=-float(r.line) if r.side==home else float(r.line)
        e=round((MH[r.matchup]-hl)*(1 if r.side==home else -1),1)   # points of edge toward the logged side; below 0 = model now on the other side
        L.at[i,'gap']=e;L.at[i,'grade']='A' if e>=5 else 'B' if e>=3 else 'C' if e>=1.5 else 'D'
have=set(zip(L.week,L.matchup))
if os.environ.get('NFL_NO_NEW_BETS')=='1':Bd=Bd.iloc[0:0]   # automatic refreshes regrade the log but never add bets to it
new=[dict(week=x.week,matchup=x.matchup,side=x.side,line=x.line,grade=x.grade,gap=x.gap,side_margin='',result='',logged=TODAY) for x in Bd.itertuples() if x.grade in('A','B') and (x.week,x.matchup) not in have]
if new:L=pd.concat([L,pd.DataFrame(new)],ignore_index=True)
L[LC].to_csv('nfl_bet_log.csv',index=False);print(L[LC].tail(8).to_string())
