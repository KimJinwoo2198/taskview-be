import argparse
import asyncio
import getpass
import os

import asyncpg

from taskview_be.auth import password_hash
from taskview_be.auth_schemas import SignUpRequest
from taskview_be.store import store


async def create_user(email: str, display_name: str, password: str, role: str) -> None:
    validated = SignUpRequest(email=email, display_name=display_name, password=password)
    await store.start()
    try:
        user = await store.create_user(
            email=str(validated.email),
            display_name=validated.display_name,
            password_hash=password_hash.hash(validated.password),
            role=role,
        )
    except asyncpg.UniqueViolationError as exc:
        raise SystemExit("이미 가입된 이메일입니다. 기존 사용자의 역할은 직접 검토해 변경하세요.") from exc
    finally:
        await store.stop()
    print(f"created {user.email} ({user.role})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a privileged TaskView user")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--role", choices=["data_owner", "admin"], required=True)
    parser.add_argument(
        "--password-env",
        default="TASKVIEW_NEW_USER_PASSWORD",
        help="Environment variable containing the password; prompts when unset",
    )
    args = parser.parse_args()
    password = os.environ.get(args.password_env) or getpass.getpass("Password: ")
    asyncio.run(create_user(args.email, args.name, password, args.role))


if __name__ == "__main__":
    main()
