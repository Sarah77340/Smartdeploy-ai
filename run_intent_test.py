from engine.pipeline0 import parse_intent

intent = parse_intent(
    "Ajoute un PC02 sur Site1 avec IP 192.168.10.20 dans VLAN10",
    known_sites=["Site1", "Site2"]
)

print(intent)
