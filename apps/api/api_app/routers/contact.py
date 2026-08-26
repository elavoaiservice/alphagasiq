from __future__ import annotations

from enum import Enum

from fastapi import APIRouter
from pydantic import BaseModel, EmailStr, Field

from ..deps import AppStateDep

router = APIRouter(prefix="/contact", tags=["contact"])


class InquiryType(str, Enum):
    GENERAL = "GENERAL"
    SALES = "SALES"
    PARTNERSHIP = "PARTNERSHIP"
    MEDIA = "MEDIA"
    SUPPORT = "SUPPORT"
    OTHER = "OTHER"


class ContactInquiryRequest(BaseModel):
    """Business-inquiry form only. This model has no field, and this router no code
    path, that can create a `User`, `Organization`, or `MagicLinkToken` — see
    docs/access-model.md "No Self-Registration". Submitting this form never creates
    an AlphaGasIQ account or provides platform access."""

    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    business_email: EmailStr
    company_name: str = Field(min_length=1, max_length=200)
    job_title: str | None = Field(default=None, max_length=150)
    phone: str | None = Field(default=None, max_length=50)
    inquiry_type: InquiryType = InquiryType.GENERAL
    message: str = Field(min_length=1, max_length=4000)


@router.post("")
async def submit_contact_inquiry(body: ContactInquiryRequest, state: AppStateDep) -> dict:
    await state.repo.save_contact_inquiry(
        first_name=body.first_name,
        last_name=body.last_name,
        business_email=str(body.business_email),
        company_name=body.company_name,
        job_title=body.job_title,
        phone=body.phone,
        inquiry_type=body.inquiry_type.value,
        message=body.message,
    )
    return {
        "detail": "Thank you for contacting AlphaGasIQ. Our team will respond to your inquiry shortly. "
        "Submitting this form does not create an AlphaGasIQ account or provide platform access."
    }
