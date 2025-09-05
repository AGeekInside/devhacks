#!/usr/bin/env python3
import docker

def list_exposed_ports():
    client = docker.from_env()

    containers = client.containers.list(all=True)

    if not containers:
        print("No containers found.")
        return

    for container in containers:
        container_info = container.attrs
        ports = container_info['NetworkSettings']['Ports']
        print(f"\nContainer: {container.name} ({container.short_id})")
        if not ports:
            print("  No ports exposed.")
        else:
            for port, mappings in ports.items():
                if mappings:
                    for mapping in mappings:
                        host_ip = mapping.get('HostIp', 'N/A')
                        host_port = mapping.get('HostPort', 'N/A')
                        print(f"  {port} -> {host_ip}:{host_port}")
                else:
                    print(f"  {port} -> Not published to host")

if __name__ == "__main__":
    list_exposed_ports()
