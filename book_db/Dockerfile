FROM postgres:15

# init.sql을 컨테이너 초기화 디렉토리에 복사
# postgres 이미지는 첫 부팅 시 /docker-entrypoint-initdb.d/*.sql을 자동 실행
COPY init.sql /docker-entrypoint-initdb.d/init.sql
