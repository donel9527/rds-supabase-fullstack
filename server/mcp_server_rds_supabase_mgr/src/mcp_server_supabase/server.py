from huaweicloud_mcp_core.server import build_server
from mcp_server_supabase.tools.planning import register

mcp = build_server("supabase")
register(mcp)

from mcp_server_supabase.tools.operations import register as register_operations
register_operations(mcp)

from mcp_server_supabase.tools.network import register as register_network
register_network(mcp)

from mcp_server_supabase.tools.billing import register as register_billing
register_billing(mcp)

from mcp_server_supabase.tools.eip import register as register_eip
register_eip(mcp)

from mcp_server_supabase.tools.obs import register as register_obs
register_obs(mcp)

from mcp_server_supabase.tools.creation_flow import register as register_creation_flow
register_creation_flow(mcp)

from mcp_server_supabase.tools.ssl_cert import register as register_ssl_cert
register_ssl_cert(mcp)

# Product input validation precedes shared argument logging and SDK coercion.
import os
from huaweicloud_mcp_core.guardrails.middleware import GuardrailsMiddleware
from mcp_server_supabase.tools.input_contract import InputContractMiddleware

guard_index = next(i for i, item in enumerate(mcp.middleware) if isinstance(item, GuardrailsMiddleware))
mcp.middleware.insert(guard_index, InputContractMiddleware(mcp, os.getenv("HUAWEICLOUD_MCP_AUDIT_FILE")))
