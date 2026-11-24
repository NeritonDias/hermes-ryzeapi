"""Configure non-secret deployment options using the Python environment of Hermes."""
import argparse,importlib.util,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('_ryze_setup',root/'__init__.py',submodule_search_locations=[str(root)])
module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
from _ryze_setup.infrastructure import validate,save,webapp_origin

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public-origin',help='Defaults to webapp.public_url in the active Hermes profile')
    parser.add_argument('--webhook-url',help='Defaults to /ryzeapi/events on the Webapp origin')
    parser.add_argument('--listener-port',type=int,default=9131)
    parser.add_argument('--listener-host', choices=('127.0.0.1','0.0.0.0'))
    parser.add_argument('--lifecycle', choices=('auto','systemd','coolify'), default='auto')
    parser.add_argument('--owner-subject', default='')
    parser.add_argument('--owner-issuer', default='')
    parser.add_argument('--gateway-service',default='hermes-gateway.service')
    parser.add_argument('--webhook-label',default='hermes-ryzeapi')
    parser.add_argument('--check',action='store_true',help='Validate only; do not write')
    args=vars(parser.parse_args());check=args.pop('check')
    args['listener_host'] = args['listener_host'] or ('0.0.0.0' if args['lifecycle'] == 'coolify' else '127.0.0.1')
    args['public_origin'] = args['public_origin'] or webapp_origin()
    if not args['public_origin']:
        parser.error('Set webapp.public_url in Hermes or provide --public-origin')
    args['webhook_url'] = args['webhook_url'] or args['public_origin'].rstrip('/')+'/ryzeapi/events'
    try:value=validate(args)
    except (ValueError,TypeError,AttributeError) as exc:parser.error(str(exc))
    if not value['webhook_url']:parser.error('A public HTTPS webhook URL is required')
    if not check:
        save(value)
    print('Validated.' if check else 'Deployment configuration saved. Restart your dashboard and gateway to apply it. No credentials or firewall settings were changed.')
if __name__=='__main__':main()
