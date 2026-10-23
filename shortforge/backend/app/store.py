"""프로젝트 저장소.

- 본문: data/projects/{id}/project.json (단일 진실 원천)
- 스냅샷: data/projects/{id}/versions/v{n}.json (버전 히스토리, F-W5 기반)
- 인덱스: data/shortforge.db (SQLite, 목록 조회용)
"""

from __future__ import annotations

import json
import re
import secrets
import shutil
import time
from datetime import datetime
from pathlib import Path, PurePosixPath

from sqlmodel import Field, Session, SQLModel, create_engine, select

from app.schemas.project import STEP_IDS, Input, Project, utcnow


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


def _rmtree(path: Path) -> None:
    """Windows에서 백신·인덱서가 파일을 잠깐 잡고 있으면 실패하므로 몇 번 다시 시도한다."""
    for attempt in range(REPLACE_RETRIES):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
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
    parent_id: str | None = None
    variant: str | None = None
    stages: str = ""  # 단계 상태를 쉼표로 이은 것 (홈 목록의 진행 막대)
    thumb: str | None = None  # 첫 장면 이미지 경로 (프로젝트 폴더 기준)


# 예전 DB에 없는 열을 추가한다 (SQLModel create_all은 기존 테이블을 바꾸지 않는다)
_ROW_MIGRATIONS = {
    "parent_id": "TEXT",
    "variant": "TEXT",
    "stages": "TEXT DEFAULT ''",
    "thumb": "TEXT",
}


def _row_summary(project: Project) -> tuple[str, str | None]:
    stages = ",".join(project.status[s].value for s in STEP_IDS)
    thumb = next((a.image.path for a in project.assets or [] if a.image.path), None)
    return stages, thumb


class ProjectStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.projects_dir = self.data_dir / "projects"
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{self.data_dir / 'shortforge.db'}")
        SQLModel.metadata.create_all(self.engine)
        with self.engine.begin() as conn:
            have = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(projects)")}
            added = [col for col in _ROW_MIGRATIONS if col not in have]
            for col in added:
                typ = _ROW_MIGRATIONS[col]
                conn.exec_driver_sql(f"ALTER TABLE projects ADD COLUMN {col} {typ}")
        if "stages" in added:
            self._backfill_summaries()

    def _backfill_summaries(self) -> None:
        """요약 열이 새로 생긴 DB는 저장된 project.json에서 한 번 채운다."""
        with Session(self.engine) as s:
            for row in s.exec(select(ProjectRow)):
                try:
                    row.stages, row.thumb = _row_summary(self.load(row.id))
                except (ProjectNotFound, ValueError):
                    continue
                s.add(row)
            s.commit()

    def project_dir(self, project_id: str) -> Path:
        # ID는 URL에서 그대로 들어온다. 형식을 강제하지 않으면 ".."로 data/ 밖을 가리킬 수 있다.
        if not PROJECT_ID.fullmatch(project_id or ""):
            raise ProjectNotFound(project_id)
        return self.projects_dir / project_id

    @staticmethod
    def new_id() -> str:
        return f"prj_{secrets.token_hex(6)}"

    def create(self, input: Input | None = None) -> Project:
        project = Project(id=self.new_id(), input=input)
        return self.save(project)

    def copy_media(self, src_id: str, dst_id: str) -> None:
        """업로드한 사진 폴더(media/)를 복사한다. user_media의 상대 경로가 그대로 맞는다."""
        src = self.project_dir(src_id) / "media"
        if src.is_dir():
            shutil.copytree(src, self.project_dir(dst_id) / "media", dirs_exist_ok=True)

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
            row.parent_id, row.variant = saved.parent_id, saved.variant
            row.version = saved.version
            row.updated_at = saved.updated_at
            row.stages, row.thumb = _row_summary(saved)
            s.add(row)
            s.commit()
        return saved

    def list(self) -> list[ProjectRow]:
        with Session(self.engine) as s:
            return list(s.exec(select(ProjectRow).order_by(ProjectRow.updated_at.desc())))

    def versions(self, project_id: str) -> list[int]:
        vdir = self.project_dir(project_id) / "versions"
        return sorted(int(p.stem[1:]) for p in vdir.glob("v*.json"))

    def version_summaries(self, project_id: str, limit: int = 30) -> list[dict]:
        """최근 버전부터 목록 (UI용 요약)."""
        out = []
        for n in reversed(self.versions(project_id)[-limit:]):
            p = self.load_version(project_id, n)
            out.append(
                {
                    "version": n,
                    "updated_at": p.updated_at.isoformat(),
                    "status": {k: v.value for k, v in p.status.items()},
                    "title": p.strategy.titles[0] if p.strategy else None,
                    "has_render": p.render is not None,
                }
            )
        return out

    def delete(self, project_id: str) -> None:
        """프로젝트 폴더와 목록 행을 지운다. 되돌릴 수 없다."""
        pdir = self.project_dir(project_id)
        if not (pdir / "project.json").exists():
            raise ProjectNotFound(project_id)
        _rmtree(pdir)
        with Session(self.engine) as s:
            row = s.get(ProjectRow, project_id)
            if row is not None:
                s.delete(row)
                s.commit()

    def referenced_files(self, project_id: str) -> set[str]:
        """현재 본문과 모든 버전이 가리키는 파일 경로 (프로젝트 폴더 기준, posix).

        버전을 되돌려도 깨지지 않도록 예전 버전이 쓰던 파일도 남긴다.
        음성의 어절 타이밍(`*.words.json`)은 렌더가 음성 경로에서 이름으로 찾으므로 함께 남긴다.
        """
        pdir = self.project_dir(project_id)
        refs: set[str] = set()

        def walk(node) -> None:
            if isinstance(node, dict):
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)
            elif isinstance(node, str) and "/" in node:
                refs.add(node.replace("\\", "/"))

        for f in [pdir / "project.json", *sorted((pdir / "versions").glob("v*.json"))]:
            walk(json.loads(f.read_text(encoding="utf-8")))
        refs |= {str(PurePosixPath(r).with_suffix(".words.json")) for r in refs if "." in r}
        return refs

    def cleanup(self, project_id: str) -> dict:
        """assets/·media/에서 어떤 버전도 가리키지 않는 파일을 지운다.

        고르지 않은 후보, 다시 만들기 전 이미지 같은 것이 쌓인다.
        """
        pdir = self.project_dir(project_id)
        refs = self.referenced_files(project_id)
        removed, freed = 0, 0
        for sub in ("assets", "media"):
            for f in sorted((pdir / sub).rglob("*")) if (pdir / sub).is_dir() else []:
                if not f.is_file() or f.relative_to(pdir).as_posix() in refs:
                    continue
                size = f.stat().st_size
                try:
                    f.unlink()
                except PermissionError:
                    continue  # 다른 프로그램이 열고 있으면 다음 정리 때 지운다
                removed, freed = removed + 1, freed + size
        return {"removed": removed, "freed_bytes": freed}

    def load_version(self, project_id: str, version: int) -> Project:
        path = self.project_dir(project_id) / "versions" / f"v{version}.json"
        if not path.exists():
            raise ProjectNotFound(f"{project_id}@v{version}")
        return Project.model_validate_json(path.read_text(encoding="utf-8"))
