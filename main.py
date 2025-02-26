from fastapi import FastAPI, WebSocket, Request, WebSocketDisconnect, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
import uuid
import json

# Initialize FastAPI app
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Database setup (SQLite)
DATABASE_URL = "sqlite:///./chat.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Define Chat Message Model
class ChatMessage(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, index=True)
    message = Column(String)

# Create tables
Base.metadata.create_all(bind=engine)

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Connection Manager for WebSockets
class ConnectionManager:
    def __init__(self):
        self.active_connections = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        connection_id = str(uuid.uuid4())
        self.active_connections[connection_id] = websocket
        await self.send_message(websocket, json.dumps({"isMe": True, "data": "You have joined!", "username": "System"}))

    async def send_message(self, ws: WebSocket, message: str):
        await ws.send_text(message)

    async def broadcast(self, websocket: WebSocket, data: str, db: Session):
        decoded_data = json.loads(data)
        message_obj = ChatMessage(username=decoded_data['username'], message=decoded_data['message'])

        # Save message in the database
        db.add(message_obj)
        db.commit()

        for connection in self.active_connections.values():
            is_me = connection == websocket
            await connection.send_text(json.dumps({
                "isMe": is_me,
                "data": decoded_data['message'],
                "username": decoded_data['username']
            }))

    def disconnect(self, websocket: WebSocket):
        for connection_id, conn in list(self.active_connections.items()):
            if conn == websocket:
                del self.active_connections[connection_id]
                break

# Initialize connection manager
connection_manager = ConnectionManager()

# Serve chat page
@app.get("/", response_class=HTMLResponse)
def get_room(request: Request, db: Session = Depends(get_db)):
    messages = db.query(ChatMessage).all()
    return templates.TemplateResponse("index.html", {"request": request, "messages": messages})

# WebSocket Endpoint
@app.websocket("/message")
async def websocket_endpoint(websocket: WebSocket, db: Session = Depends(get_db)):
    await connection_manager.connect(websocket)

    try:
        while True:
            data = await websocket.receive_text()
            await connection_manager.broadcast(websocket, data, db)
    except WebSocketDisconnect:
        connection_manager.disconnect(websocket)

# Fetch all messages (API endpoint)
@app.get("/messages")
def get_messages(db: Session = Depends(get_db)):
    return db.query(ChatMessage).all()
