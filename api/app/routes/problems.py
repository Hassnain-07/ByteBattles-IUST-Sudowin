import io
import json
import zipfile
from pydantic import ValidationError

from fastapi import APIRouter, Depends, status, HTTPException, UploadFile, Form, File, Query
from sqlalchemy.orm import Session
from typing import List, Dict, BinaryIO

from ..schemas.problems import ProblemResponse, ProblemDetailResponse, ProblemArrayDataValidator, TagCreate, TagResponse, ProblemCreateResponse, ProblemUpdate, RejudgeResponse
from ..utils import oauth2
from ..utils.redis_utils import enqueue_job
from ..database import get_db

from shared.core import get_storage_testcases, get_storage_submission_code
from shared.models import (
    Problem, Category, TestCase, # problems
    Submission, # submissions
    User, # users
    Difficulty, Verdict # enums
)

router = APIRouter(
    prefix='/problems',
    tags=["Problems"]
)

@router.post('/tag', status_code=status.HTTP_201_CREATED, response_model=TagResponse)
def create_tag(tag: TagCreate, db: Session = Depends(get_db), current_user: User = Depends(oauth2.get_current_admin)):
    if db.query(Category).filter(Category.slug == tag.slug).first():
        raise HTTPException(detail="Tag with this slug already exists", status_code=status.HTTP_409_CONFLICT)

    category = Category(name=tag.name, slug=tag.slug)

    db.add(category)
    db.commit()
    db.refresh(category)

    return category

@router.get('/', status_code=status.HTTP_200_OK, response_model=List[ProblemResponse])
def get_problems(page: int = Query(default=1, ge=1), limit: int = Query(default=20, ge=5, le=100), db: Session = Depends(get_db), current_user: User | None = Depends(oauth2.get_optional_current_admin)):
    offset = (page - 1) * limit
    if current_user:
        problems = db.query(Problem).order_by(Problem.id.asc()).offset(offset).limit(limit).all()
    else:
        problems = db.query(Problem).filter(Problem.visibility == True).order_by(Problem.id.asc()).offset(offset).limit(limit).all()

    return [
        {
            "id": problem.id,
            "title": problem.title,
            "difficulty": problem.difficulty,
            "tags": [tag.slug for tag in problem.tags],
            "accepted_submissions": problem.accepted_submissions
        }
        for problem in problems
    ]

@router.get('/{problem_id}', status_code=status.HTTP_200_OK, response_model=ProblemDetailResponse)
def get_problem_by_id(problem_id: str, db: Session = Depends(get_db), current_user: User | None = Depends(oauth2.get_optional_current_admin)):
    if current_user:
        problem = db.query(Problem).filter(Problem.id == problem_id).first()
    else:
        problem = db.query(Problem).filter(Problem.id == problem_id, Problem.visibility == True).first()
    
    if not problem:
        raise HTTPException(detail="requested problem doesn't exist", status_code=status.HTTP_404_NOT_FOUND)
    
    return {
        "id": problem.id,
        "title": problem.title,
        "difficulty": problem.difficulty,
        "tags": [tag.slug for tag in problem.tags],
        "accepted_submissions": problem.accepted_submissions,

        "description": problem.description,
        "constraints": problem.constraints,
        "input_desc": problem.input_desc,
        "output_desc": problem.output_desc,
        "sample_io": problem.sample_io,
        "explanation": problem.explanation,

        "memory_limit_mb": problem.memory_limit_mb,
        "time_limit_sec": problem.time_limit_sec,

        "source": problem.source,
        "editorial": problem.editorial,
        "visibility": problem.visibility
    }

@router.post('/', status_code=status.HTTP_201_CREATED, response_model=ProblemCreateResponse)
async def create_problem(
    id: str = Form(...),
    title: str = Form(...),
    description: str = Form(...),
    difficulty: Difficulty = Form(...),
    constraints: str = Form(...),
    tags: str = Form(...),
    sample_io: str = Form(...),

    input_desc: str = Form(...),
    output_desc: str = Form(...),
    explanation: str | None = Form(None),

    memory_limit_mb: int = Form(...),
    time_limit_sec: int = Form(...),

    visibility: bool = Form(False),
    source: str | None = Form(None),
    editorial: str | None = Form(None),

    tests_zip: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(oauth2.get_current_admin)
):
    
    # Validating Problem Id
    problem = db.query(Problem).filter(Problem.id == id).first()
    if problem:
        raise HTTPException(detail="Problem with key already exists", status_code=status.HTTP_400_BAD_REQUEST)
    
    # Validate Zip Files
    if not tests_zip.filename.endswith(".zip"):
        raise HTTPException(detail="Only ZIP files are allowed", status_code=status.HTTP_400_BAD_REQUEST)

    zip_bytes = await tests_zip.read()

    try:
        zip_file = zipfile.ZipFile(
            io.BytesIO(zip_bytes)
        )
    except zipfile.BadZipFile:
        raise HTTPException(detail="Invalid ZIP file", status_code=status.HTTP_400_BAD_REQUEST)

    # Validate Required Folders
    all_files = zip_file.namelist()
    prefix = tests_zip.filename.split(".")[0]

    input_files = sorted([
        f for f in all_files
        if f.startswith(prefix + "/inputs/")
        and not f.endswith("/")
    ])

    output_files = sorted([
        f for f in all_files
        if f.startswith(prefix + "/outputs/")
        and not f.endswith("/")
    ])

    if not input_files or not output_files:
        zip_file.close()
        raise HTTPException(detail="ZIP must contain inputs/ and outputs/", status_code=status.HTTP_400_BAD_REQUEST)
    if len(input_files) != len(output_files):
        zip_file.close()
        raise HTTPException(detail="Mismatch between input and output files", status_code=status.HTTP_400_BAD_REQUEST)
    
    for input_file, output_file in zip(input_files, output_files):
        if input_file.split("/")[-1] != output_file.split("/")[-1]:
            zip_file.close()
            raise HTTPException(detail="Mismatch in input and output file name. Each input file should have a corespoinding output file", status_code=status.HTTP_400_BAD_REQUEST)
    
    # Validating Array Data
    try:
        array_data = ProblemArrayDataValidator(
            tags=json.loads(tags),
            constraints=json.loads(constraints),
            sample_io=json.loads(sample_io)
        )
    except (json.JSONDecodeError, ValidationError):
        zip_file.close()
        raise HTTPException(detail="Invalid format for tags, constraints, or sample_io", status_code=status.HTTP_400_BAD_REQUEST)
    
    categories = db.query(Category).filter(Category.slug.in_(array_data.tags)).all()
    if len(categories) != len(array_data.tags):
        zip_file.close()
        raise HTTPException(detail="One or more tags are invalid", status_code=status.HTTP_400_BAD_REQUEST)

    # Create Problem
    problem = Problem(
        id=id,
        title=title,
        description=description,
        difficulty=difficulty,

        constraints=array_data.constraints,
        tags=categories,
        sample_io=array_data.sample_io,

        input_desc=input_desc,
        output_desc=output_desc,
        explanation=explanation,

        memory_limit_mb=memory_limit_mb,
        time_limit_sec=time_limit_sec,

        visibility=visibility,
        source=source,
        editorial=editorial
    )

    try:
        db.add(problem)
        db.flush()

        # Upload Testcases
        for input_path, output_path in zip(
            input_files,
            output_files
        ):
            input_data = zip_file.read(input_path)
            output_data = zip_file.read(output_path)

            input_key = get_storage_testcases().upload_bytes(
                problem_id=problem.id,
                filename=input_path.split("/")[-1],
                data=input_data
            )

            output_key = get_storage_testcases().upload_bytes(
                problem_id=problem.id,
                filename=output_path.split("/")[-1],
                data=output_data
            )

            testcase = TestCase(
                problem_id=problem.id,
                input_key=input_key,
                output_key=output_key
            )
            db.add(testcase)
        
        db.commit()
    except Exception:
        db.rollback()
        get_storage_testcases().delete_problem_folder(problem.id)
        raise HTTPException(detail="Unknown Error Occurred", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        zip_file.close()

    return {
        "id": problem.id,
        "title": problem.title,
        "difficulty": problem.difficulty,
        "tags": [category.slug for category in problem.tags],
        "testcases": len(input_files)
    }

@router.patch('/{problem_id}', status_code=status.HTTP_200_OK, response_model=ProblemDetailResponse)
def update_problem(problem_id: str, updates: ProblemUpdate, db: Session = Depends(get_db), current_user: User = Depends(oauth2.get_current_admin)):
    problem = db.query(Problem).filter(Problem.id == problem_id).first()
    if not problem:
        raise HTTPException(detail="Problem with given ID not found", status_code=status.HTTP_404_NOT_FOUND)

    data = updates.model_dump(exclude_unset=True)

    # Required columns can't be cleared, only changed
    nullable_fields = {"explanation", "source", "editorial"}
    for field, value in data.items():
        if value is None and field not in nullable_fields:
            raise HTTPException(detail=f"{field} cannot be null", status_code=status.HTTP_400_BAD_REQUEST)

    if "tags" in data:
        tags = data.pop("tags")
        categories = db.query(Category).filter(Category.slug.in_(tags)).all()
        if len(categories) != len(set(tags)):
            raise HTTPException(detail="One or more tags are invalid", status_code=status.HTTP_400_BAD_REQUEST)
        problem.tags = categories

    for field, value in data.items():
        setattr(problem, field, value)

    db.commit()
    db.refresh(problem)

    return get_problem_by_id(problem.id, db, current_user)

@router.delete('/{problem_id}', status_code=status.HTTP_204_NO_CONTENT)
def delete_problem(problem_id: str, current_user: User = Depends(oauth2.get_current_admin), db: Session = Depends(get_db)):
    problem = db.query(Problem).filter(Problem.id == problem_id).first()
    if not problem:
        raise HTTPException(detail="Problem with given ID not found", status_code=status.HTTP_404_NOT_FOUND)
    
    submissions = db.query(Submission).filter(Submission.problem_id == problem.id).all()
    for submission in submissions:
        get_storage_submission_code().delete_file(submission.code_object_key)
    
    get_storage_testcases().delete_problem_folder(problem.id)
    
    db.delete(problem)
    db.commit()

@router.post('/{problem_id}/rejudge', status_code=status.HTTP_202_ACCEPTED, response_model=RejudgeResponse)
def rejudge_problem(problem_id: str, current_user: User = Depends(oauth2.get_current_admin), db: Session = Depends(get_db)):
    problem = db.query(Problem).filter(Problem.id == problem_id).first()
    if not problem:
        raise HTTPException(detail="Problem with given ID not found", status_code=status.HTTP_404_NOT_FOUND)

    submissions = db.query(Submission).filter(Submission.problem_id == problem.id).order_by(Submission.id.asc()).all()
    for submission in submissions:
        submission.verdict = Verdict.PENDING
        submission.output = None
        submission.incorrect_testcase_key = None
        submission.walltime_ms = None
        submission.memory_kb = None

    # The judge re-counts accepted submissions as verdicts come back
    problem.accepted_submissions = 0
    db.commit()

    for submission in submissions:
        enqueue_job(submission.id)

    return {
        "problem_id": problem.id,
        "requeued": len(submissions)
    }
