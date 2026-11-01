# Roundtable

Roundtable is a local web app for starting a group conversation with two AI models. Pick models available to your Azure AI Foundry resource, deploy them from the app, give each AI its own display name and custom instructions, and let them take turns responding to you and to each other.

The app uses a single HTML/CSS/JavaScript frontend and a Python FastAPI backend. The backend serves the page, retrieves model and deployment metadata from Azure Resource Manager, creates deployments, checks deployment status, and sends chat requests to Foundry.

## Features

- Search models available to the configured Foundry account.
- Create a deployment for either AI seat and monitor its provisioning status.
- Customize each AI with a display name and instructions.
- Alternate model replies using the shared conversation history.
- Keep previous chats in the browser's local storage.
- Keep the Foundry API key on the backend.

## Requirements

- Python 3.10 or later.
- An Azure subscription and Microsoft Foundry resource.
- Azure CLI installed and signed in.
- Permission to list models and create deployments on the Foundry resource. Deployment creation requires **Cognitive Services Contributor** or an equivalent role.
- A Foundry resource key for inference.

## Setup

Clone the repository and open PowerShell in the project directory:

```powershell
git clone https://github.com/SPidrmAN99/Roundtable.git
Set-Location Roundtable
```

### 1. Create and activate a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, use:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```powershell
python -m pip install -r requirements.txt
```

### 3. Sign in to Azure

```powershell
az login
az account list --output table
az account set --subscription "YOUR_SUBSCRIPTION_ID"
```

Complete any required multifactor authentication. The signed-in account must have deployment permissions on the Foundry resource.

### 4. Create local environment settings

Copy the example file to a private local file:

```powershell
Copy-Item .env.example .env.local
```

Edit `.env.local` and replace the placeholders:

```env
FOUNDRY_ENDPOINT=https://YOUR-RESOURCE.services.ai.azure.com
FOUNDRY_API_KEY=your-resource-key

AZURE_SUBSCRIPTION_ID=your-subscription-id
AZURE_RESOURCE_GROUP=your-resource-group
AZURE_ACCOUNT_NAME=your-foundry-resource-name
```

`AZURE_ACCOUNT_NAME` must match the resource name in `FOUNDRY_ENDPOINT`. Use the resource root as the endpoint; do not append `/api/projects/...` or `/openai/v1`.

The application loads `.env.local` first. Both `.env` and `.env.local` are excluded from Git; `.env.example` contains placeholders only. Do not commit or share `.env.local`.

### 5. Start the app

```powershell
python -m uvicorn app:app --reload
```

Open http://127.0.0.1:8000. FastAPI's interactive API documentation is at http://127.0.0.1:8000/docs.

## Using Roundtable

1. Search the model list and select a model for AI One.
2. Select **Deploy model**, choose a deployment name, SKU, and capacity, then submit. Azure provisioning can take time. Review Azure pricing before creating deployments because they can incur charges.
3. Repeat for AI Two.
4. Optionally set custom instructions and display names for each AI.
5. Send a message. Roundtable sends the shared conversation history to each model in alternating turns. Messages you send while the models are responding are included on a later turn.
6. Start a new chat or return to a previous chat from the sidebar.

Chat history and per-seat display names and instructions are stored in the browser's local storage. They are not currently synchronized across browsers or users.

## Backend routes

| Route | Purpose |
| --- | --- |
| `GET /api/models` | Lists models and deployment choices for the configured Foundry account. |
| `POST /api/deployments` | Creates a deployment after validating the model, SKU, and capacity. |
| `GET /api/deployments/{deployment_name}` | Checks deployment provisioning status. |
| `POST /api/chat` | Sends one chat completion to a deployed model. |

## Notes

- Deployment availability, SKU, capacity, and provisioning time vary by model, region, and quota.
- A model must be deployed successfully before chat inference can use its deployment name.
- Azure credentials are used by the backend for Resource Manager operations. The Foundry resource key is used for model inference.
- This is an early prototype; it does not yet include user accounts, server-side chat storage, or production deployment hardening.
