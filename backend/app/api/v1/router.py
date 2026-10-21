from fastapi import APIRouter

from app.api.v1 import admin, auth, public

api_router = APIRouter()
api_router.include_router(public.router, tags=["public"])
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(admin.router, tags=["admin"])
