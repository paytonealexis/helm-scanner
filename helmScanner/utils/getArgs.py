import argparse
import sys
from envDefault import EnvDefault

def add_parser_args(parser):
    parser.add_argument('--artifacthub-token', action=EnvDefault, envvar='ARTIFACTHUB_TOKEN', required=True, help="Your artifacthub.io token")
    parser.add_argument('--artifacthub-secret', action=EnvDefault, envvar='ARTIFACTHUB_TOKEN_SECRET', required=True, help="Your artifacthub.io API token secret.")
    parser.add_argument('--bridgecrew-api-key', action=EnvDefault, envvar='BC_API_KEY',required=True, help="Your Bridgecrew API key for container image scanning.")
    parser.add_argument('--start-record', action=EnvDefault, envvar='START_RECORD', default=0, required=False, help="Constrain the crawler to a subset of the results by result number.")
    parser.add_argument('--max-record', action=EnvDefault, envvar='MAX_RECORD', default=300, required=False, help="Number of records to parse from --start-record")
    parser.add_argument('--result-bucket', default="NONE", required=False, help="The destination S3 bucket if .CSV output is required.")
    #return parser


parser = argparse.ArgumentParser(description='helm-scanner, IaC security data collection V2')
add_parser_args(parser)
config = parser.parse_args(sys.argv[1:])
args = parser.parse_args()
