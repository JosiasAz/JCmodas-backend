#!/usr/bin/env bash
# Atualiza a API no servidor com o código que está no GitHub (branch main).
# Roda sozinho pelo GitHub Actions a cada push na main (.github/workflows/publicar.yml).
# Também dá para rodar à mão, dentro do servidor:  bash deploy/atualizar.sh
set -euo pipefail

# tudo dentro de uma função: o bash lê o arquivo inteiro antes de começar,
# então o próprio script pode ser atualizado pelo git no meio da execução sem se perder
main() {
  cd "$(dirname "$0")/.." # pasta backend

  echo ">> Baixando o código novo"
  git fetch --quiet origin main
  # só avança; se alguém mexeu nos arquivos direto no servidor, para aqui em vez de sobrescrever
  git merge --ff-only origin/main
  echo "   versão: $(git log --oneline -1)"

  echo ">> Instalando dependências"
  .venv/bin/pip install --quiet --disable-pip-version-check -r requirements.txt

  echo ">> Reiniciando a API"
  sudo -n systemctl restart jcmoda-api

  for _ in $(seq 1 20); do
    if curl -fsS http://127.0.0.1:8000/api/health > /dev/null 2>&1; then
      echo ">> API no ar"
      return 0
    fi
    sleep 1
  done

  echo "!! A API não voltou depois de reiniciar. Últimos registros:"
  sudo -n journalctl -u jcmoda-api -n 40 --no-pager || true
  return 1
}

main "$@"
