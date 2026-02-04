"""CLI entry point for Granola Bridge."""

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from granola_bridge import __version__
from granola_bridge.config import load_config, set_config
from granola_bridge.models import init_db


def setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler()],
    )


def cmd_run(args: argparse.Namespace) -> None:
    """Run the daemon."""
    from granola_bridge.core.daemon import Daemon

    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    config = load_config(Path(args.config) if args.config else None)
    set_config(config)
    init_db()

    logger.info(f"Starting Granola Bridge v{__version__}")
    logger.info(f"Watching: {config.get_granola_cache_path()}")
    logger.info(f"Database: {config.get_database_path()}")

    daemon = Daemon(config)

    # Handle shutdown signals
    def handle_shutdown(signum, frame):
        logger.info("Received shutdown signal, stopping...")
        daemon.stop()

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    try:
        asyncio.run(daemon.run())
    except KeyboardInterrupt:
        logger.info("Interrupted, shutting down...")


def cmd_web(args: argparse.Namespace) -> None:
    """Run the web dashboard."""
    import uvicorn
    from granola_bridge.web.app import create_app

    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    config = load_config(Path(args.config) if args.config else None)
    set_config(config)
    init_db()

    logger.info(f"Starting web dashboard at http://{config.web.host}:{config.web.port}")

    app = create_app()
    uvicorn.run(app, host=config.web.host, port=config.web.port)


def cmd_process(args: argparse.Namespace) -> None:
    """Process a single transcript file or text."""
    from granola_bridge.services.action_extractor import ActionExtractor
    from granola_bridge.services.llm_client import LLMClient
    from granola_bridge.services.trello_client import TrelloClient

    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    config = load_config(Path(args.config) if args.config else None)
    set_config(config)
    init_db()

    # Read transcript
    if args.file:
        transcript = Path(args.file).read_text()
        title = Path(args.file).stem
    else:
        logger.error("Please provide a file with --file")
        sys.exit(1)

    logger.info(f"Processing transcript: {title}")

    async def process():
        llm = LLMClient(config)
        extractor = ActionExtractor(llm)
        trello = TrelloClient(config)

        action_items = await extractor.extract(title, transcript)
        logger.info(f"Found {len(action_items)} action items")

        if not args.dry_run:
            for item in action_items:
                card = await trello.create_card(
                    name=item.title,
                    desc=f"**Context:** {item.context}\n\n{item.description}",
                )
                logger.info(f"Created card: {card['url']}")
        else:
            for item in action_items:
                logger.info(f"  - {item.title} (assignee: {item.assignee})")

    asyncio.run(process())


def cmd_init(args: argparse.Namespace) -> None:
    """Initialize the database and config."""
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    config = load_config(Path(args.config) if args.config else None)
    set_config(config)

    # Create database
    db_path = config.get_database_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    init_db()
    logger.info(f"Database initialized at: {db_path}")

    # Create example config if needed
    config_dir = Path.home() / ".granola-bridge"
    config_file = config_dir / "config.yaml"
    if not config_file.exists():
        config_dir.mkdir(parents=True, exist_ok=True)
        example_config = Path(__file__).parent.parent.parent / "config.yaml.example"
        if example_config.exists():
            config_file.write_text(example_config.read_text())
            logger.info(f"Config created at: {config_file}")
        else:
            logger.info(f"Create config at: {config_file}")


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="granola-bridge",
        description="Monitor Granola meeting transcripts and create Trello cards",
    )
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-c", "--config", help="Path to config.yaml")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Run command
    run_parser = subparsers.add_parser("run", help="Run the background daemon")
    run_parser.set_defaults(func=cmd_run)

    # Web command
    web_parser = subparsers.add_parser("web", help="Run the web dashboard only")
    web_parser.set_defaults(func=cmd_web)

    # Process command
    process_parser = subparsers.add_parser("process", help="Process a single transcript")
    process_parser.add_argument("-f", "--file", help="Transcript file to process")
    process_parser.add_argument(
        "-n", "--dry-run", action="store_true", help="Don't create Trello cards"
    )
    process_parser.set_defaults(func=cmd_process)

    # Init command
    init_parser = subparsers.add_parser("init", help="Initialize database and config")
    init_parser.set_defaults(func=cmd_init)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
