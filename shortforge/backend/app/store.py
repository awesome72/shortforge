"""프로젝트 저장소.

- 본문: data/projects/{id}/project.json (단일 진실 원천)
- 스냅샷: data/projects/{id}/versions/v{n}.json (버전 히스토리, F-W5 기반)
- 인덱스: data/shortforge.db (SQLite, 목록 조회용)
"""

from __future__ import annotations

import re
import secrets
import time
from datetime import datetime
from pathlib import Path

from sqlmodel import Field, Session, SQLModel, create_engine, select

from app.schemas.project import Input, Project, utcnow


class ProjectNotFound(KeyError):
    pass


PROJECT_ID = re.compile(r"prj_[0-9a-f]{12}")


REPLACE_RETRIES = 20
REPLACE_BACKOFF_SEC = 0.025


def _atomic_write(path: Path, body: str) -> None:
    """임시 파일에 쓴 뒤 교체한다.

    Windows에서는 백신·인덱서가 대상 파일을 잠깐 열고 있으면 교체가 PermissionError로
    실패하므로 짧게 기다렸다가 다시 시도한다.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    for attempt in range(REPLACE_RETRIES):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if attempt == REPLACE_RETRIES - 1:
                raise
            time.sleep(REPLACE_BACKOFF_SEC * (attempt + 1))


class ProjectRow(SQLModel, table=True):
    __tablename__ = "projects"

    id: str = Field(primary_key=True)
    topic: str
    version: int
    updated_at: datetime


class ProjectStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.projects_dir = self.data_dir / "projects"
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{self.data_dir / 'shortforge.db'}")
        SQLModel.metadata.create_all(self.engine)

    def project_dir(self, project_id: str) -> Path:
        # ID는 URL에서 그대로 들어온다. 형식을 강제하지 않으면 ".."로 data/ 밖을 가리킬 수 있다.
        if not PROJECT_ID.fullmatch(project_id or ""):
            raise ProjectNotFound(project_id)
        return self.projects_dir / project_id

    def create(self, input: Input | None = None) -> Project:
        project = Project(id=f"prj_{secrets.token_hex(6)}", input=input)
        return self.save(project)

    def load(self, project_id: str) -> Project:
        path = self.project_dir(project_id) / "project.json"
        if not path.exists():
            raise ProjectNotFound(project_id)
        return Project.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, project: Project, *, snapshot: bool = True) -> Project:
        """버전을 1 올리고 본문·인덱스를 저장한다. snapshot이면 versions/에도 남긴다.

        실행 중(running) 같은 일시적인 상태는 snapshot=False로 저장한다.
        """
        saved = project.model_copy(update={"version": project.version + 1, "updated_at": utcnow()})
        pdir = self.project_dir(saved.id)
        (pdir / "versions").mkdir(parents=True, exist_ok=True)
        body = saved.model_dump_json(indent=2)
        _atomic_write(pdir / "project.json", body)
        if snapshot:
            (pdir / "versions" / f"v{saved.version}.json").write_text(body, encoding="utf-8")

        with Session(self.engine) as s:
            row = s.get(ProjectRow, saved.id) or ProjectRow(
                id=saved.id, topic="", version=0, updated_at=saved.updated_at
            )
            row.topic = saved.input.topic if saved.input else ""
            row.version = saved.version
            row.updated_at = saved.updated_at
            s.add(row)
            s.commit()
        return saved

    def list(self) -> list[ProjectRow]:
        with Session(self.engine) as s:
            return list(s.exec(select(ProjectRow).order_by(ProjectRow.updated_at.desc())))

    def versions(self, project_id: str) -> list[int]:
        vdir = self.project_dir(project_id) / "versions"
        return sorted(int(p.stem[1:]) for p in vdir.glob("v*.json"))

    def load_version(self, project_id: str, version: int) -> Project:
        path = self.project_dir(project_id) / "versions" / f"v{version}.json"
        if not path.exists():
            raise ProjectNotFound(f"{project_id}@v{version}")
        return Project.model_validate_json(path.read_text(encoding="utf-8"))
