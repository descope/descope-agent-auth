"""LangChain agent whose tools fetch their own credentials from Descope.

The agent runs autonomously (client credentials, no user in the loop), and each tool
pulls the exact token it needs at call time:

  * ``query_internal_api`` -> a Descope **Resource token** (your own API, protected by
    Descope OAuth scopes), minted from the agent's identity via token-exchange.
  * ``lookup_shared_crm``  -> a **tenant-level Connection** API key (one org-shared
    credential every user shares -- no per-user auth) fetched from the Descope vault.

The token never reaches the model: the LLM only ever sees a tool's *result*.

    pip install -r requirements.txt 'langchain>=1.0' 'langchain-openai>=0.2'
    set -a; source ../.env; set +a          # DESCOPE_* + TENANT_ID
    export OPENAI_API_KEY=sk-...
    python langchain_agent.py "look up Acme Corp, then check the internal API for their plan"
"""

from __future__ import annotations

import sys

from _config import base_url, optional, preview, require

from langchain.agents import create_agent
from langchain_core.tools import tool

from descope_agent_auth import AgentAuthClient, ClientCredentialsProvider


def main() -> None:
    # One autonomous client for the whole agent. Client credentials can mint Resource
    # tokens (scoped to the agent) and read tenant-level Connection tokens.
    client = AgentAuthClient(
        project_id=require("DESCOPE_PROJECT_ID"),
        base_url=base_url(),
        credential=ClientCredentialsProvider(
            client_id=require("DESCOPE_CLIENT_ID"),
            client_secret=require("DESCOPE_CLIENT_SECRET"),
        ),
    )
    resource = optional("RESOURCE", "urn:my-api")
    crm_connection = optional("CONNECTION_NAME", "salesforce")
    tenant_id = require("TENANT_ID")

    @tool
    def query_internal_api(path: str) -> str:
        """Call the company's internal API at `path` (e.g. '/customers/acme/plan')."""
        token = client.resources.get_token(resource=resource, scopes=["read"])
        # Real call (your internal API trusts Descope-issued OAuth tokens):
        #   r = httpx.get(f"https://internal.acme.com{path}",
        #                 headers={"Authorization": f"Bearer {token.access_token}"})
        #   return r.text
        return f"[demo] GET {path} with resource token {preview(token.access_token)}"

    @tool
    def lookup_shared_crm(company: str) -> str:
        """Look up `company` in the org's shared CRM (one org-wide connection)."""
        token = client.connections.get_tenant_token(
            connection=crm_connection, tenant_id=tenant_id
        )
        # Real call (org-shared API key from the vault):
        #   r = httpx.get("https://api.crm.example/v1/accounts", params={"q": company},
        #                 headers={"Authorization": f"Bearer {token.access_token}"})
        #   return r.text
        return f"[demo] search CRM for {company!r} with org key {preview(token.access_token)}"

    agent = create_agent(
        model=f"openai:{optional('OPENAI_MODEL', 'gpt-4o-mini')}",
        tools=[query_internal_api, lookup_shared_crm],
        system_prompt="You are an internal assistant. Use the tools to answer.",
    )

    question = sys.argv[1] if len(sys.argv) > 1 else "Look up Acme Corp in the CRM."
    result = agent.invoke({"messages": [{"role": "user", "content": question}]})
    print("\n=== answer ===")
    print(result["messages"][-1].content)


if __name__ == "__main__":
    main()
