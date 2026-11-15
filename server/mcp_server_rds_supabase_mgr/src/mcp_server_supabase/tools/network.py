from huaweicloud_mcp_core.security import ToolRisk,guard
from mcp_server_supabase.service.network import Network

def register(server):
    service=Network()

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def list_supabase_security_groups(limit:int=10,marker:str|None=None)->dict:
        """查询可用于 RDS Supabase 应用的安全组清单（分页）。单页返回、需逐页遍历；供创建应用或换绑安全组前查找并选定既有分组，规则明细以单组查询为准。"""
        return await service.list_groups(limit,marker)

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def show_supabase_security_group(group_id:str)->dict:
        """查询单个安全组的完整规则集（方向、协议、端口与源地址）。供接线 RDS Supabase 应用前核对放行面，或规则增删前后比对影响。"""
        return await service.show_group(group_id)

    @server.tool()
    @guard(risk=ToolRisk.WRITE)
    async def create_supabase_security_group(name:str,description:str|None=None,confirm:bool=False,plan_id:str|None=None)->dict:
        """创建 RDS Supabase 应用专用安全组，两段式提交。自动打 AUTO_CREATE 与 USE_FOR 双标签，仅此类分组可被本流程删除；应填写用途描述以便审计。"""
        return await service.create_group(name,description,confirm,plan_id)

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def add_supabase_security_group_rule(group_id:str,source_cidr:str,port:int=8443,direction:str='ingress',protocol:str='tcp',confirm:bool=False,plan_id:str|None=None)->dict:
        """为安全组新增一条端口放行规则，两段式提交。拒收 0.0.0.0/0 等全网入方向源；共享安全组的规则变更影响邻居实例，确认后方可执行。"""
        return await service.add_rule(group_id,source_cidr,port,direction,protocol,confirm,plan_id)

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def delete_supabase_security_group_rule(group_id:str,rule_id:str,confirm:bool=False,plan_id:str|None=None)->dict:
        """删除安全组的单条放行规则，用于收窄开放面（如撤销失效 CIDR），两段式提交。规则经所有权校验归属；删除可能中断在线流量，确认后方可执行。"""
        return await service.delete_rule(group_id,rule_id,confirm,plan_id)

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def delete_supabase_security_group(group_id:str,confirm:bool=False,plan_id:str|None=None)->dict:
        """删除整个安全组，两段式提交。标签门禁：仅本流程创建（AUTO_CREATE/USE_FOR 标签）且无引用的分组可删，其余一律拒绝；仍在使用的分组由后端拒绝。"""
        return await service.delete_group(group_id,confirm,plan_id)
