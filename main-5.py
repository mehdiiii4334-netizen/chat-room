import os, io, uuid, random, time, hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import FastAPI, HTTPException, Depends, WebSocket, WebSocketDisconnect, UploadFile, File, Query, Header
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey, Boolean, or_, and_
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, Session
from passlib.context import CryptContext
from jose import jwt, JWTError
from PIL import Image, ImageDraw, ImageFont, ImageFilter

APP_SECRET = os.getenv('APP_SECRET', 'CHANGE_THIS_SECRET_BEFORE_DEPLOYMENT_please_32_chars')
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./gapkhune.db')
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
connect_args = {'check_same_thread': False} if DATABASE_URL.startswith('sqlite') else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()
pwd = CryptContext(schemes=['bcrypt'], deprecated='auto')
ALGORITHM = 'HS256'

class User(Base):
    __tablename__='users'
    id=Column(Integer, primary_key=True)
    username=Column(String(32), unique=True, index=True, nullable=False)
    display_name=Column(String(60), nullable=False)
    password_hash=Column(String(255), nullable=False)
    bio=Column(String(180), default='')
    avatar=Column(String(500), default='')
    created_at=Column(DateTime, default=datetime.utcnow)
    is_active=Column(Boolean, default=True)
class Conversation(Base):
    __tablename__='conversations'
    id=Column(Integer, primary_key=True)
    title=Column(String(80), default='')
    kind=Column(String(12), default='group')
    created_by=Column(Integer, ForeignKey('users.id'))
    created_at=Column(DateTime, default=datetime.utcnow)
class Membership(Base):
    __tablename__='memberships'
    id=Column(Integer, primary_key=True)
    conversation_id=Column(Integer, ForeignKey('conversations.id'), index=True)
    user_id=Column(Integer, ForeignKey('users.id'), index=True)
    role=Column(String(12), default='member')
class Message(Base):
    __tablename__='messages'
    id=Column(Integer, primary_key=True)
    conversation_id=Column(Integer, ForeignKey('conversations.id'), index=True)
    sender_id=Column(Integer, ForeignKey('users.id'))
    body=Column(Text, nullable=False)
    created_at=Column(DateTime, default=datetime.utcnow, index=True)
Base.metadata.create_all(engine)

app=FastAPI(title='GapKhune', version='2.0.0')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])
app.mount('/static', StaticFiles(directory='static'), name='static')
CAPTCHAS={}
ONLINE={}

def db_session():
    db=SessionLocal()
    try: yield db
    finally: db.close()
def make_token(user_id:int):
    return jwt.encode({'sub':str(user_id),'exp':datetime.now(timezone.utc)+timedelta(days=7)}, APP_SECRET, algorithm=ALGORITHM)
def get_user(token:str, db:Session):
    try:
        data=jwt.decode(token, APP_SECRET, algorithms=[ALGORITHM]); uid=int(data['sub'])
    except Exception: raise HTTPException(401, 'نشست شما معتبر نیست؛ دوباره وارد شوید')
    user=db.get(User,uid)
    if not user or not user.is_active: raise HTTPException(401,'حساب کاربری پیدا نشد')
    return user
def auth_header(authorization:Optional[str]=Header(default=None), db:Session=Depends(db_session)):
    if not authorization or not authorization.startswith('Bearer '): raise HTTPException(401,'ابتدا وارد حساب شوید')
    return get_user(authorization[7:],db)

class AuthIn(BaseModel):
    username:str=Field(min_length=3,max_length=32, pattern=r'^[a-zA-Z0-9_]+$')
    password:str=Field(min_length=8,max_length=72)
    captcha_id:str
    captcha_answer:str
    display_name:Optional[str]=None
class ProfileIn(BaseModel):
    display_name:str=Field(min_length=1,max_length=60)
    bio:str=Field(default='',max_length=180)
class GroupIn(BaseModel):
    title:str=Field(min_length=2,max_length=80)
    usernames:list[str]=[]
class MessageIn(BaseModel):
    body:str=Field(min_length=1,max_length=4000)
class DirectIn(BaseModel):
    username:str

def check_captcha(cid, answer):
    item=CAPTCHAS.pop(cid,None)
    if not item or item[1] < time.time() or item[0].lower()!=answer.strip().lower():
        raise HTTPException(400,'کد امنیتی اشتباه یا منقضی شده است')

@app.get('/')
def home():
    return HTMLResponse(open('static/index.html',encoding='utf-8').read())
@app.get('/api/health')
def health(): return {'ok':True,'app':'GapKhune','version':'2.0'}
@app.get('/api/captcha')
def captcha():
    code=''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789',k=5)); cid=str(uuid.uuid4())
    CAPTCHAS[cid]=(code,time.time()+300)
    im=Image.new('RGB',(170,58),(244,247,252)); d=ImageDraw.Draw(im)
    for _ in range(7):
        d.line((random.randint(0,170),random.randint(0,58),random.randint(0,170),random.randint(0,58)),fill=(random.randint(90,180),random.randint(90,180),random.randint(90,180)),width=1)
    try: font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',27)
    except: font=ImageFont.load_default()
    d.text((22,12),' '.join(code),font=font,fill=(25,48,80),stroke_width=0)
    out=io.BytesIO(); im.save(out,format='PNG'); out.seek(0)
    return {'captcha_id':cid,'image':'data:image/png;base64,'+__import__('base64').b64encode(out.read()).decode()}
@app.post('/api/register')
def register(data:AuthIn,db:Session=Depends(db_session)):
    check_captcha(data.captcha_id,data.captcha_answer)
    if db.query(User).filter_by(username=data.username.lower()).first(): raise HTTPException(409,'این نام کاربری قبلاً ثبت شده است')
    user=User(username=data.username.lower(),display_name=(data.display_name or data.username).strip(),password_hash=pwd.hash(data.password))
    db.add(user); db.commit(); db.refresh(user)
    return {'token':make_token(user.id),'user':user_data(user)}
@app.post('/api/login')
def login(data:AuthIn,db:Session=Depends(db_session)):
    check_captcha(data.captcha_id,data.captcha_answer)
    user=db.query(User).filter_by(username=data.username.lower()).first()
    if not user or not pwd.verify(data.password,user.password_hash): raise HTTPException(401,'نام کاربری یا رمز عبور اشتباه است')
    return {'token':make_token(user.id),'user':user_data(user)}
def user_data(u): return {'id':u.id,'username':u.username,'display_name':u.display_name,'bio':u.bio,'avatar':u.avatar}
@app.get('/api/me')
def me(user:User=Depends(auth_header)): return user_data(user)
@app.put('/api/me')
def update_profile(data:ProfileIn,db:Session=Depends(db_session),user:User=Depends(auth_header)):
    user=db.get(User,user.id); user.display_name=data.display_name.strip(); user.bio=data.bio.strip(); db.commit(); return user_data(user)
@app.get('/api/users')
def search_users(q:str='',db:Session=Depends(db_session),user:User=Depends(auth_header)):
    rows=db.query(User).filter(User.id!=user.id,or_(User.username.contains(q.lower()),User.display_name.contains(q))).limit(30).all()
    return [user_data(x) for x in rows]
def is_member(db,cid,uid): return db.query(Membership).filter_by(conversation_id=cid,user_id=uid).first() is not None
@app.get('/api/conversations')
def conversations(db:Session=Depends(db_session),user:User=Depends(auth_header)):
    memberships=db.query(Membership).filter_by(user_id=user.id).all(); out=[]
    for m in memberships:
        c=db.get(Conversation,m.conversation_id)
        if not c: continue
        members=db.query(Membership).filter_by(conversation_id=c.id).all()
        other=None
        if c.kind=='direct':
            for mm in members:
                if mm.user_id!=user.id: other=db.get(User,mm.user_id); break
        last=db.query(Message).filter_by(conversation_id=c.id).order_by(Message.id.desc()).first()
        out.append({'id':c.id,'kind':c.kind,'title':(other.display_name if other else c.title),'username':(other.username if other else ''),'avatar':(other.avatar if other else ''),'last_message':last.body if last else 'هنوز پیامی نیست','last_at':last.created_at.isoformat() if last else c.created_at.isoformat(),'members':len(members)})
    return sorted(out,key=lambda x:x['last_at'],reverse=True)
@app.post('/api/groups')
def create_group(data:GroupIn,db:Session=Depends(db_session),user:User=Depends(auth_header)):
    c=Conversation(title=data.title.strip(),kind='group',created_by=user.id); db.add(c); db.commit(); db.refresh(c)
    db.add(Membership(conversation_id=c.id,user_id=user.id,role='admin'))
    for name in set(data.usernames):
        target=db.query(User).filter_by(username=name.lower()).first()
        if target and target.id!=user.id: db.add(Membership(conversation_id=c.id,user_id=target.id))
    db.commit(); return {'id':c.id,'title':c.title}
@app.post('/api/direct')
def direct(data:DirectIn,db:Session=Depends(db_session),user:User=Depends(auth_header)):
    target=db.query(User).filter_by(username=data.username.lower()).first()
    if not target or target.id==user.id: raise HTTPException(404,'کاربر پیدا نشد')
    existing=db.query(Conversation).filter_by(kind='direct').all()
    for c in existing:
        ids={m.user_id for m in db.query(Membership).filter_by(conversation_id=c.id).all()}
        if ids=={user.id,target.id}: return {'id':c.id}
    c=Conversation(kind='direct',title=''); db.add(c); db.commit(); db.refresh(c)
    db.add_all([Membership(conversation_id=c.id,user_id=user.id),Membership(conversation_id=c.id,user_id=target.id)]); db.commit()
    return {'id':c.id}
@app.get('/api/conversations/{cid}/messages')
def messages(cid:int,before:int=0,db:Session=Depends(db_session),user:User=Depends(auth_header)):
    if not is_member(db,cid,user.id): raise HTTPException(403,'عضو این گفتگو نیستید')
    q=db.query(Message).filter(Message.conversation_id==cid)
    if before: q=q.filter(Message.id<before)
    rows=q.order_by(Message.id.desc()).limit(60).all(); rows.reverse()
    return [{'id':m.id,'body':m.body,'sender_id':m.sender_id,'sender':db.get(User,m.sender_id).display_name,'created_at':m.created_at.isoformat()} for m in rows]
@app.post('/api/conversations/{cid}/messages')
async def send_message(cid:int,data:MessageIn,db:Session=Depends(db_session),user:User=Depends(auth_header)):
    if not is_member(db,cid,user.id): raise HTTPException(403,'عضو این گفتگو نیستید')
    m=Message(conversation_id=cid,sender_id=user.id,body=data.body.strip()); db.add(m); db.commit(); db.refresh(m)
    payload={'type':'message','message':{'id':m.id,'body':m.body,'sender_id':user.id,'sender':user.display_name,'created_at':m.created_at.isoformat(),'conversation_id':cid}}
    import asyncio
    for ws in list(ONLINE.get(cid,[])):
        try: await ws.send_json(payload)
        except: pass
    return payload['message']
@app.websocket('/ws/{cid}')
async def websocket_chat(ws:WebSocket,cid:int,token:str=Query(...)):
    db=SessionLocal()
    try:
        try: u=get_user(token,db)
        except: await ws.close(code=4401); return
        if not is_member(db,cid,u.id): await ws.close(code=4403); return
        await ws.accept(); ONLINE.setdefault(cid,[]).append(ws)
        await ws.send_json({'type':'connected','user_id':u.id})
        while True: await ws.receive_text()
    except WebSocketDisconnect: pass
    finally:
        if ws in ONLINE.get(cid,[]): ONLINE[cid].remove(ws)
        db.close()
@app.post('/api/avatar')
async def upload_avatar(file:UploadFile=File(...),db:Session=Depends(db_session),user:User=Depends(auth_header)):
    if file.content_type not in ('image/jpeg','image/png','image/webp'): raise HTTPException(400,'فقط عکس JPG، PNG یا WEBP مجاز است')
    data=await file.read()
    if len(data)>3*1024*1024: raise HTTPException(400,'حجم عکس باید کمتر از ۳ مگابایت باشد')
    ext='png' if file.content_type=='image/png' else ('webp' if file.content_type=='image/webp' else 'jpg')
    name=f'{uuid.uuid4().hex}.{ext}'; os.makedirs('uploads',exist_ok=True); path=os.path.join('uploads',name)
    with open(path,'wb') as f:f.write(data)
    u=db.get(User,user.id); u.avatar='/uploads/'+name; db.commit(); return {'avatar':u.avatar}
app.mount('/uploads',StaticFiles(directory='uploads',check_dir=False),name='uploads')
