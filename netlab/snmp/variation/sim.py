# snmpsim variation module: dynamic values from simcore.  Record: <oid>|<tag>:sim|k=...,d=...
import os, sys, time
sys.path.insert(0, os.getenv("SIMCORE_PATH", "/srv"))
from simcore import SIM


def init(**context):
    pass


def variate(oid, tag, value, **context):
    if not context["nextFlag"] and not context["exactMatch"]:
        return context["origOid"], tag, context["errorStatus"]
    if context["setFlag"]:
        return context["origOid"], tag, context["errorStatus"]
    if "spec" not in recordContext:
        recordContext["spec"] = dict(x.split("=", 1) for x in value.split(","))
    return oid, tag, SIM.snmp_value(recordContext["spec"], time.time())


def shutdown(**context):
    pass
