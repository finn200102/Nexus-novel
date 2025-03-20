from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.database import engine, Base
from app.routers import auth, novel, library, chapter
# Import other routers as needed

# Create database tables
Base.metadata.create_all(bind=engine)

# Initialize FastAPI app
app = FastAPI(
    title="Your API",
    description="API description",
    version="0.1.0"
)

# Configure CORS if needed
origins = [
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:5173"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router)
app.include_router(novel.router)
app.include_router(library.router)
app.include_router(chapter.router)
# Include other routers as needed

# Root endpoint
@app.get("/")
async def root():
    return {"message": "Welcome to Your API"}
