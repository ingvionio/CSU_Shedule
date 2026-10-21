"""Вход администратора."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.core.security import AuthError, authenticate_admin
from app.schemas.admin import LoginIn, TokenOut

router = APIRouter()


@router.post("/auth/admin/login", response_model=TokenOut, summary="Вход администратора, выдача JWT")
def admin_login(data: LoginIn) -> TokenOut:
    try:
        token, expires_at = authenticate_admin(data.login, data.password)
    except AuthError as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(error)) from error
    return TokenOut(access_token=token, expires_at=expires_at)
