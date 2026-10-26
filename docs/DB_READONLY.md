# 팀원 DB 읽기 전용 접속

수집은 kic-agent-data 의 GitHub Actions 가 관리자 계정으로 합니다. 팀원과 이 저장소의 코드는 **읽기 전용 계정(`agent_reader`)** 으로만 접속합니다.
그래서 실수로 테이블을 지우거나 수집 데이터를 바꿀 수 없습니다.

## 관리자가 한 번만 할 일 (Neon 콘솔)

1. Neon 콘솔 → 프로젝트 → **Roles** → New role → 이름 `agent_reader` → 비밀번호 복사.
2. **SQL Editor** 에서 관리자 계정으로 아래를 실행합니다.

```sql
GRANT USAGE ON SCHEMA core, rag TO agent_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA core, rag TO agent_reader;
-- 앞으로 수집 코드가 새로 만드는 테이블·뷰도 자동으로 읽기 허용
ALTER DEFAULT PRIVILEGES IN SCHEMA core, rag GRANT SELECT ON TABLES TO agent_reader;
-- 혹시 쓰기 시도가 있어도 막히도록
ALTER ROLE agent_reader SET default_transaction_read_only = on;
```

`ALTER DEFAULT PRIVILEGES` 는 테이블을 만드는 역할(수집 계정) 기준으로 적용됩니다. 수집 계정으로 실행하세요.
`ops`(작업 상태)와 `raw`(원본 백업)는 Agent 가 쓰지 않으므로 열지 않습니다.

3. **Connection Details** 에서 Role 을 `agent_reader` 로 바꾸고 접속 주소를 복사합니다.
4. 그 주소를 팀원에게 **개인 메시지로만** 보냅니다 (이슈·PR·공개 채팅 금지).

## 팀원이 할 일

1. `.env.example` 을 `.env` 로 복사합니다.
2. 받은 주소를 `DATABASE_URL=` 뒤에 붙여 넣습니다.
3. 확인:

```bash
python -c "from agent.db import query; print(query('check', 'SELECT count(*) AS n FROM core.company').rows)"
```

숫자가 나오면 성공입니다.

## 주의

- 주소가 유출되면 관리자가 Neon 콘솔에서 `agent_reader` 비밀번호를 재설정하고 다시 나눠 줍니다.
- 무거운 질의는 `statement_timeout`(15초)에 걸립니다. 집계는 가능한 한 DB 뷰로 만들어 달라고 수집 담당에게 요청하세요.
