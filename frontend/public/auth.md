# RagReader auth.md

## Overview

RagReader provides authentication and registration protocols for AI agents to interact with hybrid retrieval-augmented generation, multi-hop document research, and query pipelines.

- **Audience**: AI Agents, Code Assistants, and Automated Systems
- **Resource Identifier**: `https://rag.nevatal.id`
- **Authorization Server**: `https://rag.nevatal.id`
- **Registration Endpoint**: `https://rag.nevatal.id/api/agent/register`
- **Token Endpoint**: `https://rag.nevatal.id/api/auth/token`
- **Supported Methods**: Bearer Token (`Authorization: Bearer <token>`)
- **Supported Scopes**: `read`, `write`, `rag`, `mcp`

## Agent Registration Flow

Agents can register or provision an API token:

```http
POST /api/agent/register HTTP/1.1
Host: rag.nevatal.id
Content-Type: application/json

{
  "client_name": "MyRagAgent",
  "client_uri": "https://example.com/agent"
}
```

Response:
```json
{
  "access_token": "ragreader_agent_token_sample",
  "token_type": "Bearer",
  "expires_in": 2592000,
  "scope": "read write rag mcp"
}
```

## Discovery Endpoints

- OAuth Authorization Server Metadata: [/.well-known/oauth-authorization-server](https://rag.nevatal.id/.well-known/oauth-authorization-server)
- OpenID Connect Configuration: [/.well-known/openid-configuration](https://rag.nevatal.id/.well-known/openid-configuration)
- OAuth Protected Resource Metadata: [/.well-known/oauth-protected-resource](https://rag.nevatal.id/.well-known/oauth-protected-resource)
- API Catalog: [/.well-known/api-catalog](https://rag.nevatal.id/.well-known/api-catalog)
- MCP Server Card: [/.well-known/mcp/server-card.json](https://rag.nevatal.id/.well-known/mcp/server-card.json)
- A2A Agent Card: [/.well-known/agent-card.json](https://rag.nevatal.id/.well-known/agent-card.json)
- Agent Skills Discovery: [/.well-known/agent-skills/index.json](https://rag.nevatal.id/.well-known/agent-skills/index.json)
