import os
from pathlib import Path
from typing import Literal

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from azure.identity import DefaultAzureCredential

PROJECT_DIR = Path(__file__).parent
load_dotenv(PROJECT_DIR / ".env.local")
load_dotenv(PROJECT_DIR / ".env")

FOUNDRY_ENDPOINT = os.getenv("FOUNDRY_ENDPOINT", "").rstrip("/")
FOUNDRY_API_KEY = os.getenv("FOUNDRY_API_KEY", "")

AZURE_SUBSCRIPTION_ID = os.getenv("AZURE_SUBSCRIPTION_ID", "")
AZURE_RESOURCE_GROUP = os.getenv("AZURE_RESOURCE_GROUP", "")
AZURE_ACCOUNT_NAME = os.getenv("AZURE_ACCOUNT_NAME", "")

ARM_API_VERSION = "2025-06-01"
ARM_SCOPE = "https://management.azure.com/.default"

app = FastAPI(title="Roundtable API")
frontend_origins = [
    origin.strip()
    for origin in os.getenv(
        "FRONTEND_ORIGINS",
        "http://127.0.0.1:8000,http://localhost:8000,https://spidrman99.github.io",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=frontend_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)
credential = DefaultAzureCredential()


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    model: str
    persona: str
    messages: list[ChatMessage]
    temperature: float = Field(default=0.8, ge=0, le=2)
    max_tokens: int = Field(default=500, ge=1, le=8000)


class DeploymentRequest(BaseModel):
    model_name: str
    model_format: str
    model_version: str
    deployment_name: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$",
    )
    sku_name: str
    capacity: int = Field(ge=1)
    publisher: str | None = None


def require_inference_settings():
    if not FOUNDRY_ENDPOINT or not FOUNDRY_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="Set FOUNDRY_ENDPOINT and FOUNDRY_API_KEY in .env.",
        )


def require_arm_settings():
    missing = [
        name for name, value in {
            "AZURE_SUBSCRIPTION_ID": AZURE_SUBSCRIPTION_ID,
            "AZURE_RESOURCE_GROUP": AZURE_RESOURCE_GROUP,
            "AZURE_ACCOUNT_NAME": AZURE_ACCOUNT_NAME,
        }.items()
        if not value
    ]
    if missing:
        raise HTTPException(
            status_code=500,
            detail=f"Missing deployment settings in .env: {', '.join(missing)}",
        )


def arm_token() -> str:
    try:
        return credential.get_token(ARM_SCOPE).token
    except Exception as exc:
        raise HTTPException(
            status_code=401,
            detail=(
                "Azure Resource Manager sign-in failed. Run 'az login' in "
                "PowerShell, then restart the backend. The signed-in account "
                "needs deployment permissions on the Foundry resource."
            ),
        ) from exc


def account_arm_path() -> str:
    return (
        f"/subscriptions/{AZURE_SUBSCRIPTION_ID}"
        f"/resourceGroups/{AZURE_RESOURCE_GROUP}"
        f"/providers/Microsoft.CognitiveServices"
        f"/accounts/{AZURE_ACCOUNT_NAME}"
    )


async def arm_request(method: str, path: str, *, params=None, json_body=None):
    headers = {"Authorization": f"Bearer {arm_token()}"}
    url = f"https://management.azure.com{path}"

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.request(
            method,
            url,
            headers=headers,
            params=params,
            json=json_body,
        )

    if not response.is_success:
        body = response.text.strip() or "(empty response)"
        raise HTTPException(
            status_code=502,
            detail=f"Azure Resource Manager returned HTTP {response.status_code}: {body[:1000]}",
        )

    return response


async def get_account_catalog():
    require_arm_settings()

    path = f"{account_arm_path()}/models"
    response = await arm_request(
        "GET",
        path,
        params={"api-version": ARM_API_VERSION},
    )
    return response.json().get("value", [])


@app.get("/api/models")
async def list_models():
    """List models and deployment choices available to this Azure account."""
    models = await get_account_catalog()

    return {
        "data": [
            {
                "id": f"{model.get('format', '')}::{model.get('name', '')}::{model.get('version', '')}",
                "name": model.get("name", ""),
                "format": model.get("format", ""),
                "version": str(model.get("version", "")),
                "publisher": model.get("publisher", ""),
                "skus": model.get("skus", []),
            }
            for model in models
            if model.get("name") and model.get("format")
        ]
    }


@app.post("/api/deployments")
async def create_deployment(request: DeploymentRequest):
    """Create a Foundry model deployment after validating it against the account catalog."""
    require_arm_settings()

    catalog = await get_account_catalog()

    selected_model = next(
        (
            model for model in catalog
            if model.get("name") == request.model_name
            and model.get("format") == request.model_format
            and str(model.get("version", "")) == request.model_version
        ),
        None,
    )

    if selected_model is None:
        raise HTTPException(
            status_code=400,
            detail="That model version isn't available for this Foundry account.",
        )

    selected_sku = next(
        (
            sku for sku in selected_model.get("skus", [])
            if sku.get("name") == request.sku_name
        ),
        None,
    )

    if selected_sku is None:
        raise HTTPException(
            status_code=400,
            detail="That deployment SKU isn't available for this model.",
        )

    capacity_rules = selected_sku.get("capacity", {})
    allowed_values = capacity_rules.get("allowedValues") or []

    if allowed_values and request.capacity not in allowed_values:
        raise HTTPException(
            status_code=400,
            detail=f"Capacity must be one of: {allowed_values}.",
        )

    minimum = capacity_rules.get("minimum")
    maximum = capacity_rules.get("maximum")
    step = capacity_rules.get("step")

    if minimum is not None and request.capacity < minimum:
        raise HTTPException(status_code=400, detail=f"Minimum capacity is {minimum}.")
    if maximum is not None and request.capacity > maximum:
        raise HTTPException(status_code=400, detail=f"Maximum capacity is {maximum}.")
    if minimum is not None and step and (request.capacity - minimum) % step != 0:
        raise HTTPException(
            status_code=400,
            detail=f"Capacity must increase in steps of {step} from {minimum}.",
        )

    model_info = {
        "format": request.model_format,
        "name": request.model_name,
        "version": request.model_version,
    }
    if request.publisher:
        model_info["publisher"] = request.publisher

    deployment_body = {
        "sku": {
            "name": request.sku_name,
            "capacity": request.capacity,
        },
        "properties": {
            "model": model_info,
        },
    }

    path = (
        f"{account_arm_path()}/deployments/"
        f"{request.deployment_name}"
    )

    response = await arm_request(
        "PUT",
        path,
        params={"api-version": ARM_API_VERSION},
        json_body=deployment_body,
    )

    result = response.json() if response.content else {}
    state = result.get("properties", {}).get("provisioningState", "Accepted")

    return {
        "deploymentName": request.deployment_name,
        "provisioningState": state,
        "message": "Deployment request accepted by Azure.",
    }


@app.get("/api/deployments/{deployment_name}")
async def get_deployment(deployment_name: str):
    """Check deployment provisioning status."""
    require_arm_settings()

    path = f"{account_arm_path()}/deployments/{deployment_name}"
    response = await arm_request(
        "GET",
        path,
        params={"api-version": ARM_API_VERSION},
    )
    result = response.json()

    return {
        "deploymentName": result.get("name", deployment_name),
        "provisioningState": result.get("properties", {}).get(
            "provisioningState", "Unknown"
        ),
        "model": result.get("properties", {}).get("model", {}),
    }


@app.post("/api/chat")
async def chat(request: ChatRequest):
    """Send an inference request to a deployed model."""
    require_inference_settings()

    url = f"{FOUNDRY_ENDPOINT}/openai/v1/chat/completions"
    headers = {
        "api-key": FOUNDRY_API_KEY,
        "Content-Type": "application/json",
    }

    payload = {
        "model": request.model,
        "messages": [
            {"role": "system", "content": request.persona},
            *[message.model_dump() for message in request.messages],
        ],
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
    }

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(url, headers=headers, json=payload)

    if not response.is_success:
        body = response.text.strip() or "(empty response)"
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Foundry chat request failed: {body[:1000]}",
        )

    return response.json()


web_folder = PROJECT_DIR / "web"
app.mount("/", StaticFiles(directory=web_folder, html=True), name="web")
