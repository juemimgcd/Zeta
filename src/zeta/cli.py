"""Command-line entry point."""

import argparse
import asyncio
from contextlib import aclosing
from typing import cast

from dotenv import load_dotenv
from pydantic_ai.exceptions import (
    ModelAPIError,
    ModelHTTPError,
    UnexpectedModelBehavior,
    UserError,
)

from zeta import __version__
from zeta.app import stream_prompt


def build_parser() -> argparse.ArgumentParser:
    """Build the single-prompt parser."""
    parser = argparse.ArgumentParser(prog="zeta")
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument("-p", "--prompt", help="send one prompt and exit")
    return parser


async def run_cli(prompt: str) -> None:
    """Print each text fragment and close the stream on failure or cancellation."""
    wrote_text = False
    try:
        async with aclosing(stream_prompt(prompt)) as stream:
            async for text in stream:
                print(text, end="", flush=True)
                wrote_text = True
    finally:
        if wrote_text:
            print(flush=True)


def main() -> None:
    """Load configuration and display a response or a safe error."""
    parser = build_parser()
    args = parser.parse_args()
    prompt = cast(str | None, args.prompt)
    if prompt is None:
        parser.error("-p/--prompt is required")
    load_dotenv(override=False)
    try:
        asyncio.run(run_cli(prompt))
    except ValueError:
        parser.exit(2, "zeta: prompt must not be empty\n")
    except UserError:
        parser.exit(2, "zeta: check DEEPSEEK_API_KEY and model configuration\n")
    except ModelHTTPError as error:
        parser.exit(1, f"zeta: DeepSeek request failed: HTTP {error.status_code}\n")
    except ModelAPIError:
        parser.exit(1, "zeta: DeepSeek request failed\n")
    except UnexpectedModelBehavior:
        parser.exit(1, "zeta: incomplete or invalid DeepSeek response\n")
    except KeyboardInterrupt:
        parser.exit(130, "zeta: cancelled\n")
