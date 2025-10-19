"""
Tado token management utility.
Handles initial authentication and token storage for Azure Functions.
"""
import os

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from dotenv import load_dotenv

from tadoclient.client import TadoClient
from tadoclient.config import TadoSettings

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

def authenticate_and_store_tokens():
    """
    Perform interactive authentication and store refresh token in Key Vault.
    Run this locally once to set up tokens for the function app.
    """
    # Create minimal settings (username/password no longer required)
    settings = TadoSettings(home_id=os.environ['TADO_HOME_ID'])
    
    # Authenticate interactively
    client = TadoClient(settings)
    client.authenticate()
    
    # Store refresh token in Key Vault
    key_vault_url = f"https://{os.environ['KEY_VAULT_NAME']}.vault.azure.net/"
    credential = DefaultAzureCredential()
    secret_client = SecretClient(vault_url=key_vault_url, credential=credential)
    
    # Store the refresh token
    print(f"Storing refresh token in Key Vault: {client._refresh_token}")
    secret_client.set_secret("tado-refresh-token", client._refresh_token)
    verify_refresh = secret_client.get_secret("tado-refresh-token").value
    if verify_refresh == client._refresh_token:
        print("Verified refresh token persisted in Key Vault.")
    else:
        print(
            f"ERROR: Refresh token mismatch after update! Expected: {client._refresh_token}, "
            f"Found: {verify_refresh}"
        )

    # Store access token temporarily (expires in 10 minutes)
    print(f"Storing access token in Key Vault: {client._access_token}")
    secret_client.set_secret("tado-access-token", client._access_token)
    verify_access = secret_client.get_secret("tado-access-token").value
    if verify_access == client._access_token:
        print("Verified access token persisted in Key Vault.")
    else:
        print(
            f"ERROR: Access token mismatch after update! Expected: {client._access_token}, "
            f"Found: {verify_access}"
        )

if __name__ == "__main__":
    authenticate_and_store_tokens()