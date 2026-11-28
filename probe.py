import json, urllib.request, urllib.parse, time
BASE='https://external-api.kalshi.com/trade-api/v2'
C='''KXNFL1QSPREAD KXNFL1QTOTAL KXNFL1H KXNFL1HWINNER KXNFL1Q KXNFL1QWINNER KXNFL1HTEAMTOTAL KXNCAAF1QSPREAD KXNCAAF1QTOTAL KXNCAAF1H KXNCAAF1HWINNER KXNCAAF1Q KXNCAAF1QWINNER KXNCAAF1HTEAMTOTAL KXNBA1HSPREAD KXNBA1HTOTAL KXNBA1H KXNBA1HWINNER KXNBA1QSPREAD KXNBA1QTOTAL KXNBA1Q KXNBA1QWINNER KXNBA1HTEAMTOTAL KXNCAAMB1HSPREAD KXNCAAMB1HTOTAL KXNCAAMB1H KXNCAAMB1HWINNER KXNCAAMB1HTEAMTOTAL KXNCAAMBHTEAMTOTAL KXNHL1P KXNHL1PSPREAD KXNHL1PTOTAL KXNFLFIRSTTD KXNFLANYTD KXNFL2TD KXNFLTD KXNFLLONGREC KXNFLLONGESTREC KXNFLLONGRSH KXNFLFG KXNFLGAMEFG KXNFLTEAMFG KXNHLGOAL KXNHLANYGOAL KXNHLFIRSTGOAL KXNHLPTS KXNHLAST KXNHLSAVES KXNHLSAVE KXUFCROUNDS KXUFCVICROUND KXNFLTEAMTD KXNCAAFTEAMTD KXNBA2D KXNBA3D KXNBABLK KXNBASTL KXNBASTOCK KXNBAFTM'''.split()
out={}
for s in C:
    try:
        u=BASE+'/events?'+urllib.parse.urlencode({'series_ticker':s,'status':'open','limit':200,'with_nested_markets':'true'})
        d=json.load(urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'probe'}),timeout=60))
        ev=d.get('events',[])
        samp=[]
        for e in ev[:2]:
            for m in e.get('markets',[])[:3]:
                samp.append({k:m.get(k) for k in ('ticker','title','yes_sub_title','no_sub_title','subtitle','floor_strike','strike_type','yes_ask_dollars','no_ask_dollars','expected_expiration_time')})
        out[s]={'n':len(ev),'title':ev[0].get('title') if ev else None,'sub':ev[0].get('sub_title') if ev else None,'mk':sum(len(e.get('markets',[])) for e in ev),'samp':samp}
    except Exception as e: out[s]={'err':str(e)}
    time.sleep(0.3)
json.dump(out,open('probe.json','w'),indent=1)
