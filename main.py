from boto.ec2.connection import EC2Connection
from time import sleep
import subprocess
import ConfigParser, os, socket
import sys

config = ConfigParser.ConfigParser()
config.read('spot-ec2-proxifier.ini')

def create_client():
        client = EC2Connection(config.get('IAM', 'access'), config.get('IAM', 'secret'))
        regions = client.get_all_regions()
        for r in regions:
                if r.name == config.get('EC2', 'region'):
                        client = EC2Connection(config.get('IAM', 'access'), config.get('IAM', 'secret'), region = r)
                        return client
        return None

def get_existing_instance(client):
        instances = client.get_all_instances(filters = { 'tag-value': config.get('EC2', 'tag') })
        if len(instances) > 0:
                return instances[0].instances[0]
        else:
                return None

def get_spot_price(client):
        price_history = client.get_spot_price_history(instance_type = config.get('EC2', 'type'), product_description = 'Linux/UNIX')
        return price_history[0].price

def provision_instance(client):
        req = client.request_spot_instances(price = config.get('EC2', 'max_bid'), 
                image_id = config.get('EC2', 'ami'), 
                instance_type = config.get('EC2', 'type'), 
                key_name = config.get('EC2', 'key_pair'), 
                security_groups = [config.get('EC2', 'security_group')])[0]
        print 'Spot request created, status: ' + req.state
        print 'Waiting for spot provisioning',
        while True:
                current_req = client.get_all_spot_instance_requests([req.id])[0]
                if current_req.state == 'active':
                        print 'done.'
                        instance = client.get_all_instances([current_req.instance_id])[0].instances[0]
                        instance.add_tag('Name', config.get('EC2', 'tag'))
                        return instance
                print '.',
                sleep(30)

def destroy_instance(client, inst):
        try:
                print 'Terminating', str(inst.id), '...',
                client.terminate_instances(instance_ids = [inst.id])
                print 'done.'
                inst.remove_tag('Name', config.get('EC2', 'tag'))
        except:
                print 'Failed to terminate:', sys.exc_info()[0]

def wait_for_up(client, inst):
        print 'Waiting for instance to come up',
        while True:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                if inst.ip_address is None:
                        inst = get_existing_instance(client)
                try:
                        if inst.ip_address is None:
                                print 'IP not assigned yet ...',
                        else:
                                s.connect((inst.ip_address, 22))
                                s.shutdown(2)
                                print 'Server is up!'
                                break
                except:
                        print '.',
                sleep(10)
        
def start_plink(inst):
        plink_cmd = 'plink -N -D ' + config.get('Proxy', 'bind_port') + ' -i ' + config.get('Proxy', 'key_file') + ' ec2-user@' + inst.ip_address
        print 'Running: ' + plink_cmd
        print 'Once connection is established, use Ctrl-C to kill the tunnel'
        plink = subprocess.call(plink_cmd, shell = False)

# Entry
action = 'start' if len(sys.argv) == 1 else sys.argv[1]

client = create_client()
if client is None:
        print 'Unable to create EC2 client'
        sys.exit(0)

inst = get_existing_instance(client)

if action == 'start':
        if inst is None:
                spot_price = get_spot_price(client)
                print 'Spot price is ' + str(spot_price) + ' ...',
                if spot_price > float(config.get('EC2', 'max_bid')):
                        print 'too high!'
                        sys.exit(0)
                else:
                        print 'below maximum bid, continuing'
                        provision_instance(client)
                        inst = get_existing_instance(client)

        wait_for_up(client, inst)
        start_plink(inst)
elif action == 'stop' and inst is not None:
        destroy_instance(client, inst)
else:
        print 'No action taken'
