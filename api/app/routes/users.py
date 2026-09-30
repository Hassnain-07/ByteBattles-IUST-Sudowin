from fastapi import APIRouter, status, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List

from ..utils import oauth2, password_manager
from ..schemas.user import UserResponse, UserUpdate, UserResponseUnknown, UserRoleUpdate, UserRoleResponse, SolvedProblemResponse
from ..schemas.submissions import SubmissionHeaderResponse
from ..database import get_db

from shared.models import User, Submission, Problem, Verdict

router = APIRouter(
    prefix='/users',
    tags=["Users"]
)

@router.get('/me', status_code=status.HTTP_200_OK, response_model=UserResponse)
def get_current_user(current_user: User = Depends(oauth2.get_current_user)):
    return current_user

@router.patch('/me', status_code=status.HTTP_200_OK, response_model=UserResponse)
def update_current_user(updates: UserUpdate, current_user: User = Depends(oauth2.get_current_user), db: Session = Depends(get_db)):

    if updates.password and updates.conf_password:
        if updates.password != updates.conf_password:
            raise HTTPException(detail="confirm password and given password don't match", status_code=status.HTTP_400_BAD_REQUEST)
        else:
            current_user.password_hash = password_manager.hash(updates.password)
    elif updates.password or updates.conf_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
    
    if updates.username:
        if current_user.username != updates.username and db.query(User).filter(User.username == updates.username).first():
            raise HTTPException(detail="username already in use", status_code=status.HTTP_409_CONFLICT)
        else:
            current_user.username = updates.username
        
    if updates.email:
        if current_user.email != updates.email and db.query(User).filter(User.email == updates.email).first():
            raise HTTPException(detail="email already in use", status_code=status.HTTP_409_CONFLICT)
        else:
            current_user.email = updates.email

    db.commit()
    db.refresh(current_user)

    return current_user

@router.delete('/me', status_code=status.HTTP_204_NO_CONTENT)
def delete_current_user(current_user: User = Depends(oauth2.get_current_user), db: Session = Depends(get_db)):
    db.delete(current_user)
    db.commit()

def get_visible_user(username: str, db: Session, current_user: User | None) -> User:
    if current_user and current_user.username == username:
        return current_user

    user = db.query(User).filter(User.username == username, User.is_verified == True).first()
    if not user:
        raise HTTPException(detail="User with the given username was not found", status_code=status.HTTP_404_NOT_FOUND)
    
    return user

@router.get('/{username}', status_code=status.HTTP_200_OK)
def get_user(username: str, db: Session = Depends(get_db), current_user: User | None = Depends(oauth2.get_optional_current_user)):
    if current_user and current_user.username == username:
        return UserResponse(
            username=current_user.username,
            email=current_user.email,
            created_at=current_user.created_at,
            is_verified=current_user.is_verified
        )

    user = get_visible_user(username, db, current_user)
    
    return UserResponseUnknown(
        username=user.username,
        is_verified=user.is_verified,
        created_at=user.created_at
    )

@router.get('/{username}/submissions', status_code=status.HTTP_200_OK, response_model=List[SubmissionHeaderResponse])
def get_user_submissions(username: str, page: int = Query(default=1, ge=1), limit: int = Query(default=20, ge=5, le=100), db: Session = Depends(get_db), current_user: User | None = Depends(oauth2.get_optional_current_user)):
    user = get_visible_user(username, db, current_user)

    offset: int = (page - 1) * limit
    submissions = (
        db.query(Submission)
        .join(Problem)
        .filter(Submission.user_id == user.id, Problem.visibility == True)
        .order_by(Submission.submitted_at.desc(), Submission.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return submissions

@router.get('/{username}/solved_problems', status_code=status.HTTP_200_OK, response_model=List[SolvedProblemResponse])
def get_user_solved_problems(username: str, db: Session = Depends(get_db), current_user: User | None = Depends(oauth2.get_optional_current_user)):
    user = get_visible_user(username, db, current_user)

    solved_ids = (
        db.query(Submission.problem_id)
        .filter(Submission.user_id == user.id, Submission.verdict == Verdict.ACCEPTED)
        .distinct()
    )
    problems = (
        db.query(Problem)
        .filter(Problem.id.in_(solved_ids), Problem.visibility == True)
        .order_by(Problem.id.asc())
        .all()
    )

    return [{"id": problem.id, "title": problem.title} for problem in problems]

@router.patch('/{username}/role', status_code=status.HTTP_200_OK, response_model=UserRoleResponse)
def update_user_role(username: str, update: UserRoleUpdate, db: Session = Depends(get_db), current_user: User = Depends(oauth2.get_current_admin)):
    if current_user.username == username:
        raise HTTPException(detail="Admins cannot change their own role", status_code=status.HTTP_400_BAD_REQUEST)

    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(detail="User with the given username was not found", status_code=status.HTTP_404_NOT_FOUND)

    user.user_type = update.user_type
    db.commit()
    db.refresh(user)

    return user
