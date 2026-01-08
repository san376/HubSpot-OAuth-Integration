# # slack.py

# from fastapi import Request

# async def authorize_hubspot(user_id, org_id):
#     # TODO
#     pass

# async def oauth2callback_hubspot(request: Request):
#     # TODO
#     pass

# async def get_hubspot_credentials(user_id, org_id):
#     # TODO
#     pass

# async def create_integration_item_metadata_object(response_json):
#     # TODO
#     pass

# async def get_items_hubspot(credentials):
#     # TODO
#     pass





# hubspot.py
import os
from dotenv import load_dotenv

load_dotenv()   # 👈 THIS IS REQUIRED

import json
import base64
import secrets
from fastapi import Request, HTTPException
from fastapi.responses import HTMLResponse
import httpx
import asyncio
from integrations.integration_item import IntegrationItem

from redis_client import add_key_value_redis, get_value_redis, delete_key_redis

# CLIENT_ID = "19c0deae-a413-4198-b181-93e492c0db4c"  # Replace with your actual Client ID
# CLIENT_SECRET = "bc5a87c2-066c-4b50-bae8-515f7ed7213c"

CLIENT_ID = os.getenv("HUBSPOT_CLIENT_ID")
CLIENT_SECRET = os.getenv("HUBSPOT_CLIENT_SECRET")


AUTH_URL = "https://app.hubspot.com/oauth/authorize"
TOKEN_URL = "https://api.hubapi.com/oauth/v1/token"

SCOPES = "crm.objects.contacts.read crm.objects.contacts.write"


async def authorize_hubspot(user_id, org_id):
    state_data = {
        "state": secrets.token_urlsafe(32),
        "user_id": user_id,
        "org_id": org_id
    }

    # encoded_state = json.dumps(state_data)
    encoded_state = base64.urlsafe_b64encode(
    json.dumps(state_data).encode("utf-8")
    ).decode("utf-8")
    await add_key_value_redis(f"hubspot_state:{org_id}:{user_id}", encoded_state, expire=600)

    redirect_uri = "http://localhost:8000/integrations/hubspot/oauth2callback"

    return (
        f"{AUTH_URL}"
        f"?client_id={CLIENT_ID}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={SCOPES}"
        f"&state={encoded_state}"
    )


async def oauth2callback_hubspot(request: Request):
    if request.query_params.get("error"):
        raise HTTPException(status_code=400, detail=request.query_params.get("error"))

    code = request.query_params.get("code")
    encoded_state = request.query_params.get("state")
    # state_data = json.loads(encoded_state)
    state_data = json.loads(
    base64.urlsafe_b64decode(encoded_state).decode("utf-8")
   )

    user_id = state_data["user_id"]
    org_id = state_data["org_id"]

    saved_state = await get_value_redis(f"hubspot_state:{org_id}:{user_id}")
    if not saved_state:
        raise HTTPException(status_code=400, detail="State expired")

    redirect_uri = "http://localhost:8000/integrations/hubspot/oauth2callback"

    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "code": code,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    token_json = token_response.json()

    await add_key_value_redis(
        f"hubspot_credentials:{org_id}:{user_id}",
        json.dumps(token_json),
        expire=3600,
    )

    await delete_key_redis(f"hubspot_state:{org_id}:{user_id}")

    # return HTMLResponse("<h1>HubSpot Authorization Successful</h1>")
    close_window_script = """
    <html>
    <script>
    window.close();
    </script>
    </html>
    """
    return HTMLResponse(content=close_window_script)



async def get_hubspot_credentials(user_id, org_id):
    creds = await get_value_redis(f"hubspot_credentials:{org_id}:{user_id}")
    if not creds:
        raise HTTPException(status_code=404, detail="No HubSpot credentials found")

    return json.loads(creds)


async def create_integration_item_metadata_object(response_json):
    return IntegrationItem(
        id=response_json["id"],
        name=response_json["properties"].get("firstname", "Unknown"),
        type="contact",
    )


# 
async def get_items_hubspot(credentials):
    credentials = json.loads(credentials)   # ✅ FIX

    access_token = credentials["access_token"]

    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://api.hubapi.com/crm/v3/objects/contacts",
            headers=headers
        )

    data = r.json()
    results = []

    for item in data.get("results", []):
        results.append(await create_integration_item_metadata_object(item))

    return results
