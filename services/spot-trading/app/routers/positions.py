from fastapi import APIRouter, Request

from ..main import db_pool
from ..repositories.position_repo import PositionRepository
from ..schemas import PositionResponse
from .orders import _get_user_id

router = APIRouter()


@router.get("/positions", response_model=list[PositionResponse])
async def get_positions(request: Request):
    user_id = _get_user_id(request)
    async with db_pool.acquire() as conn:
        pos_list = await PositionRepository(conn).list_by_user(user_id)
    return [
        PositionResponse(
            asset=p.asset,
            available=str(p.available),
            locked=str(p.locked),
            total=str(p.total),
        )
        for p in pos_list
    ]
