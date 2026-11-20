"""A2A connectivity smoke test to a locally running worker."""
import argparse,asyncio,httpx
from a2a.client import A2ACardResolver,ClientConfig,create_client
from a2a.helpers import new_text_message
from a2a.types import Role,SendMessageRequest

async def main(url):
    async with httpx.AsyncClient(timeout=20.0) as http:
        card=await A2ACardResolver(httpx_client=http,base_url=url).get_agent_card()
        print('Discovered A2A agent:',card.name)
    client=await create_client(agent=card,client_config=ClientConfig(streaming=False))
    message=new_text_message('Please inspect and acknowledge task TEST-001',role=Role.ROLE_USER)
    async for response in client.send_message(SendMessageRequest(message=message)):
        print('A2A response:',str(response)[:2000])
    await client.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:9999');args=p.parse_args();asyncio.run(main(args.url))
