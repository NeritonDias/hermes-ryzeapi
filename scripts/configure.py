"""Configure non-secret deployment options using the Python environment of Hermes."""
import argparse,importlib.util,json,os,sys,tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('_ryze_setup',root/'__init__.py',submodule_search_locations=[str(root)])
module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
from _ryze_setup.infrastructure import validate,load
from _ryze_setup.settings import directory

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public-origin',required=True)
    parser.add_argument('--webhook-url',required=True)
    parser.add_argument('--listener-port',type=int,default=9120)
    parser.add_argument('--gateway-service',default='hermes-gateway.service')
    parser.add_argument('--webhook-label',default='hermes-ryzeapi')
    parser.add_argument('--check',action='store_true',help='Validate only; do not write')
    args=vars(parser.parse_args());check=args.pop('check')
    try:value=validate(args)
    except (ValueError,TypeError,AttributeError) as exc:parser.error(str(exc))
    if not value['webhook_url']:parser.error('A public HTTPS webhook URL is required')
    if not check:
        folder=directory();folder.mkdir(mode=0o700,parents=True,exist_ok=True)
        fd,name=tempfile.mkstemp(prefix='.deployment-',dir=folder)
        try:
            with os.fdopen(fd,'w') as stream:
                json.dump(value,stream,indent=2);stream.flush();os.fsync(stream.fileno())
            os.replace(name,folder/'deployment.json')
        finally:
            if os.path.exists(name):os.unlink(name)
    print('Validated.' if check else 'Deployment configuration saved. Restart your dashboard and gateway to apply it. No credentials or firewall settings were changed.')
if __name__=='__main__':main()
