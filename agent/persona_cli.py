"""외부 키·DB 없이 실행하는 페르소나 카탈로그·분류·프롬프트 CLI."""
import argparse
import json
from pathlib import Path

from agent.personas import (
    DOMAIN_RULES,
    PersonaProfile,
    assess_questionnaire,
    build_persona_instruction,
    get_persona_catalog,
    get_questionnaire,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("catalog")
    commands.add_parser("questions")
    assess = commands.add_parser("assess")
    assess.add_argument("path", type=Path, help="knowledge_answers/style_answers/mode JSON")
    for command in ("classify", "prompt"):
        sub = commands.add_parser(command)
        sub.add_argument("--level", choices=["L1", "L2", "L3", "L4"])
        sub.add_argument("--style", choices=["A", "C"])
        sub.add_argument("--mode", choices=["combined", "literacy_only", "style_only"], default="combined")
        sub.add_argument("--confirmed", action="store_true", help="사용자가 확인한 경우만 지정")
        if command == "prompt":
            sub.add_argument("--domain", choices=list(DOMAIN_RULES), required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "catalog":
            result = get_persona_catalog()
        elif args.command == "questions":
            result = get_questionnaire()
        elif args.command == "assess":
            payload = json.loads(args.path.read_text(encoding="utf-8-sig"))
            if not isinstance(payload, dict):
                raise ValueError("설문 파일은 JSON 객체여야 합니다.")
            unknown = set(payload) - {"knowledge_answers", "style_answers", "mode"}
            if unknown:
                raise ValueError("알 수 없는 설문 필드입니다.")
            result = assess_questionnaire(**payload)
        else:
            profile = PersonaProfile(args.level, args.style, args.mode, args.confirmed)
            result = profile.to_dict()
            if args.command == "prompt":
                result["instruction"] = build_persona_instruction(profile, args.domain)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, TypeError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
