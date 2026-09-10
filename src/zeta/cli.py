import argparse
import asyncio
from pathlib import Path
from typing import cast

from dotenv import load_dotenv
from openai import APIError, APIStatusError

from zeta import __version__
from zeta.app import run_agent
from zeta.loop_common import ModelResponseError, RunLimitError
from zeta.tools import ToolError


def main() -> None:
    parser = argparse.ArgumentParser(prog="zeta")
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument("-p", "--prompt", required=True)
    args = parser.parse_args()
    prompt = cast(str, args.prompt)
    load_dotenv(override=False)
    try:
        output = asyncio.run(run_agent(prompt, Path.cwd()))
    except ValueError:
        parser.exit(2, "zeta: invalid input, model configuration or API key\n")
    except APIStatusError as error:
        parser.exit(1, f"zeta: model request failed: HTTP {error.status_code}\n")
    except APIError:
        parser.exit(1, "zeta: model request failed\n")
    except ModelResponseError:
        parser.exit(1, "zeta: incomplete or invalid model response\n")
    except (RunLimitError, ToolError) as error:
        parser.exit(1, f"zeta: {error}\n")
    except TimeoutError:
        parser.exit(1, "zeta: run timed out\n")
    except KeyboardInterrupt:
        parser.exit(130, "zeta: cancelled\n")
    print(output)