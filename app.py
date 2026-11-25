import os, secrets, hmac, math, datetime
from flask import Flask, request, session, jsonify, send_from_directory, redirect
from dotenv import load_dotenv
import psycopg
from psycopg.types.json import Jsonb
load_dotenv()
app=Flask(__name__)
app.secret_key=os.environ['SECRET_KEY']
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict', SESSION_COOKIE_SECURE=os.getenv('RENDER')=='true')
if len(app.secret_key)<32: raise RuntimeError('Configure SECRET_KEY')
def db(): return psycopg.connect(os.environ['DATABASE_URL'])
def init():
    with db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS nutrition_state (id integer PRIMARY KEY CHECK(id=1), payload jsonb NOT NULL, revision bigint NOT NULL DEFAULT 0)')
        c.execute('CREATE TABLE IF NOT EXISTS stretching_logs (log_date date NOT NULL, exercise_id smallint NOT NULL CHECK(exercise_id BETWEEN 1 AND 6), completed boolean NOT NULL, updated_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(log_date,exercise_id))')
        c.execute('INSERT INTO nutrition_state(id,payload) VALUES(1,%s) ON CONFLICT DO NOTHING',(Jsonb({'data':[],'targets':[2300,140,300,60]}),))
@app.get('/login')
def login(): return redirect('/')
@app.get('/')
def home():
    return send_from_directory(app.root_path,'index.html')
@app.after_request
def headers(r):
    r.headers['Cache-Control']='no-store'; r.headers['X-Content-Type-Options']='nosniff'; return r
@app.route('/api/state',methods=['GET','PUT'])
def state():
    if request.method=='GET':
        with db() as c: payload,rev=c.execute('SELECT payload,revision FROM nutrition_state WHERE id=1').fetchone()
        return jsonify(**payload,revision=rev,csrf=session.setdefault('csrf',secrets.token_hex(32)))
    if not hmac.compare_digest(request.headers.get('X-CSRF-Token',''),session.get('csrf','!')): return jsonify(error='CSRF'),403
    x=request.get_json(silent=True)
    def num(v): return type(v) in (int,float) and math.isfinite(v) and 0<=v<=100000
    try:
        a,t,rev=x['data'],x['targets'],x['revision']; assert isinstance(a,list) and len(a)<=100000 and len(t)==4 and all(num(v) and v>0 for v in t) and type(rev)==int
        for r in a:
            assert isinstance(r['id'],str) and isinstance(r['meal'],str) and all(num(r[k]) for k in ('p','c','f','k')); datetime.date.fromisoformat(r['day'])
        assert len({r['id'] for r in a})==len(a)
    except (TypeError,KeyError,ValueError,AssertionError,OverflowError): return jsonify(error='資料格式錯誤'),400
    with db() as c:
        row=c.execute('UPDATE nutrition_state SET payload=%s,revision=revision+1 WHERE id=1 AND revision=%s RETURNING revision',(Jsonb({'data':a,'targets':t}),rev)).fetchone()
    if not row: return jsonify(error='其他裝置已更新，請備份未儲存資料並重新整理'),409
    return jsonify(revision=row[0])
@app.route('/api/stretching', methods=['GET','PUT','POST'])
def stretching():
    if request.method=='GET':
        with db() as c:
            rows=c.execute('SELECT log_date,exercise_id,completed FROM stretching_logs ORDER BY log_date,exercise_id').fetchall()
        logs={}
        for day,i,done in rows: logs.setdefault(day.isoformat(),[False]*6)[i-1]=done
        return jsonify(logs=logs,csrf=session.setdefault('csrf',secrets.token_hex(32)))
    if not hmac.compare_digest(request.headers.get('X-CSRF-Token',''),session.get('csrf','!')): return jsonify(error='CSRF'),403
    x=request.get_json(silent=True)
    try:
        if request.method=='PUT':
            day=datetime.date.fromisoformat(x['date']); i=x['exercise_id']; done=x['completed']
            if type(i)!=int or not 1<=i<=6 or type(done)!=bool: raise ValueError()
            rows=[(day,i,done)]
        else:
            logs=x['logs']
            if not isinstance(logs,dict) or len(logs)>10000: raise ValueError()
            rows=[]
            for d,a in logs.items():
                day=datetime.date.fromisoformat(d)
                if not isinstance(a,list) or len(a)!=6 or any(type(v)!=bool for v in a): raise ValueError()
                rows.extend((day,i+1,v) for i,v in enumerate(a))
    except (TypeError,KeyError,ValueError): return jsonify(error='伸展資料格式錯誤'),400
    with db() as c:
        for row in rows:
            sql='INSERT INTO stretching_logs(log_date,exercise_id,completed) VALUES(%s,%s,%s) ON CONFLICT(log_date,exercise_id) '
            c.execute(sql+('DO NOTHING' if request.method=='POST' else 'DO UPDATE SET completed=EXCLUDED.completed,updated_at=now()'),row)
    return jsonify(ok=True)

init()
if __name__=='__main__': app.run(port=5000)
