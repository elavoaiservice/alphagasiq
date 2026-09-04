from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from .state import AppState, get_app_state

AppStateDep = Annotated[AppState, Depends(get_app_state)]
