"""위험요인 신고 API.

권한 규칙
  - 조회·생성: 로그인한 모든 사용자. 조회 범위(작업자=본인, 관리자=사업장 전체)는 DB RLS 가 정한다.
  - 수정·삭제·데모 초기화: 관리자만. FastAPI(require_manager)와 DB(RLS·컬럼 권한) 양쪽에서 막는다.
요청 본문은 extra="forbid" 라서 허용되지 않은 필드(status, reported_by, role 등)를 보내면 422 로 거부된다.
"""

from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from backend import domain
from backend.api.deps import get_current_user, get_repo, require_manager
from backend.domain import CurrentUser
from backend.ratelimit import report_limiter

router = APIRouter(prefix="/api", tags=["reports"])

Status = Literal["received", "in_progress", "completed"]


class ReportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    area: str = Field(max_length=domain.AREA_MAX + 50)  # 앞뒤 공백 제거 후 정확한 길이는 domain 에서 검사
    hazard: str = Field(max_length=domain.HAZARD_MAX + 50)


class ReportPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str | None = Field(default=None, max_length=domain.ACTION_MAX + 50)
    status: Status | None = None
    due_date: str | None = None


@router.get("/reports")
def list_reports(status: Status | None = Query(default=None), user: CurrentUser = Depends(get_current_user)):
    return get_repo().list_reports(user, status)


@router.post("/reports", status_code=201)
def create_report(body: ReportIn, user: CurrentUser = Depends(get_current_user)):
    report_limiter.hit(user.id)
    return get_repo().create_report(user, body.area, body.hazard)


@router.get("/reports/{report_id}")
def get_report(report_id: str, user: CurrentUser = Depends(get_current_user)):
    return get_repo().get_report(user, report_id)


@router.patch("/reports/{report_id}")
def update_report(report_id: str, body: ReportPatch, user: CurrentUser = Depends(require_manager)):
    changes = body.model_dump(exclude_unset=True)  # 보낸 필드만 (null 을 보내면 지우기)
    if not changes:
        raise domain.ValidationError("수정할 내용이 없습니다.")
    if changes.get("status", "") is None:
        raise domain.ValidationError("상태는 비울 수 없습니다.")
    return get_repo().update_report(user, report_id, changes)


@router.delete("/reports/{report_id}", status_code=204)
def delete_report(report_id: str, user: CurrentUser = Depends(require_manager)):
    get_repo().delete_report(user, report_id)
    return Response(status_code=204)


@router.post("/demo/reset")
def reset_demo(user: CurrentUser = Depends(require_manager)):
    return {"reports": get_repo().reset_demo(user)}
