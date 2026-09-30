"""
Guarda do scripts/update_weekly.sh no modo do launchd (--se-vencido): só roda se não
houve sucesso desde a última publicação semanal da CVM (segunda 9h), desiste depois de
MAX_TENTATIVAS falhas na semana, e o lock não deixa rodar duas cópias (nem trava para
sempre quando o dono morreu). Nenhum teste chega a rodar os ingestores.
"""
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "update_weekly.sh"
TZ = "America/Sao_Paulo"   # sem horário de verão desde 2019: datas determinísticas

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="precisa de bash")


def epoch(s: str) -> int:
    return int(datetime.fromisoformat(s).replace(tzinfo=ZoneInfo(TZ)).timestamp())


def run(log_dir, *args, agora: str, **env):
    e = {**os.environ, "TZ": TZ, "UPDATE_LOG_DIR": str(log_dir),
         "NOW_EPOCH": str(epoch(agora)), **{k: str(v) for k, v in env.items()}}
    return subprocess.run(["bash", str(SCRIPT), *args], env=e,
                          capture_output=True, text=True, timeout=60)


def carimbo(log_dir, quando: str):
    (log_dir / ".ultimo_sucesso").write_text(f"{epoch(quando)} {quando}\n")


# 2026-09-28 é segunda-feira

@pytest.mark.parametrize("sucesso, agora, vencido", [
    (None,                  "2026-09-29 10:00", True),   # nunca rodou
    ("2026-09-21 09:05",    "2026-09-28 08:59", False),  # segunda, antes das 9h: semana anterior vale
    ("2026-09-21 09:05",    "2026-09-28 09:00", True),   # publicação nova
    ("2026-09-21 09:05",    "2026-09-28 13:48", True),   # Mac ligou às 9h48: recupera no mesmo dia
    ("2026-09-28 13:48",    "2026-09-28 17:48", False),  # disparo de 4 h depois do sucesso
    ("2026-09-28 13:48",    "2026-10-04 23:00", False),  # domingo: ainda não há ZIP novo
    ("2026-09-30 15:00",    "2026-10-05 09:00", True),   # manual na quarta não empurra a janela
    ("2026-09-14 09:00",    "2026-09-27 12:00", True),   # perdeu a segunda passada inteira
])
def test_verificar_janela_semanal(tmp_path, sucesso, agora, vencido):
    if sucesso:
        carimbo(tmp_path, sucesso)
    r = run(tmp_path, "--verificar", agora=agora)
    assert r.returncode == (0 if vencido else 1), r.stdout + r.stderr
    assert ("vencida" in r.stdout) == vencido


def test_dia_e_hora_configuraveis(tmp_path):
    carimbo(tmp_path, "2026-09-28 09:05")                       # segunda
    # Publicação às terças 14h: terça 13h ainda em dia, terça 14h vencida
    assert run(tmp_path, "--verificar", agora="2026-09-29 13:00", CVM_DIA_SEMANA=2, CVM_HORA=14).returncode == 1
    assert run(tmp_path, "--verificar", agora="2026-09-29 14:00", CVM_DIA_SEMANA=2, CVM_HORA=14).returncode == 0
    # Domingo = 0
    assert run(tmp_path, "--verificar", agora="2026-10-04 10:00", CVM_DIA_SEMANA=0).returncode == 0


def test_carimbo_invalido_conta_como_nunca(tmp_path):
    (tmp_path / ".ultimo_sucesso").write_text("lixo\n")
    r = run(tmp_path, "--verificar", agora="2026-09-29 10:00")
    assert r.returncode == 0
    assert "nenhuma execução bem-sucedida" in r.stdout


def test_desiste_apos_max_tentativas_na_semana(tmp_path):
    carimbo(tmp_path, "2026-09-21 09:05")
    tent = tmp_path / ".tentativas"
    # Uma falha da semana anterior não conta; duas desta semana ainda deixam tentar
    tent.write_text(f"{epoch('2026-09-22 09:00')}\n{epoch('2026-09-28 09:05')}\n{epoch('2026-09-28 13:05')}\n")
    assert run(tmp_path, "--verificar", agora="2026-09-28 17:05").returncode == 0
    with tent.open("a") as f:
        f.write(f"{epoch('2026-09-28 17:05')}\n")
    r = run(tmp_path, "--verificar", agora="2026-09-28 21:05")
    assert r.returncode == 1
    assert "3 tentativas" in r.stdout
    # Semana seguinte volta a tentar
    assert run(tmp_path, "--verificar", agora="2026-10-05 09:00").returncode == 0


def test_se_vencido_em_dia_sai_rapido_sem_log(tmp_path):
    carimbo(tmp_path, "2026-09-28 13:48")
    r = run(tmp_path, "--se-vencido", agora="2026-09-28 17:48")
    assert r.returncode == 0
    assert "Nada a fazer" in r.stdout
    assert not list(tmp_path.glob("update_*.log"))          # não polui a rotação de logs
    assert not (tmp_path / ".update_weekly.lock").exists()   # lock liberado


def test_lock_de_execucao_viva_impede_segunda_copia(tmp_path):
    lock = tmp_path / ".update_weekly.lock"
    lock.mkdir()
    dono = subprocess.Popen(["bash", "-c", "sleep 30; : update_weekly"])
    try:
        (lock / "pid").write_text(str(dono.pid))
        r = run(tmp_path, "--se-vencido", agora="2026-09-29 10:00")   # vencida, mas em uso
        assert r.returncode == 0
        assert "em andamento" in r.stdout
        assert lock.exists() and (lock / "pid").read_text() == str(dono.pid)
    finally:
        dono.kill()
        dono.wait()


def test_lock_orfao_e_retomado(tmp_path):
    lock = tmp_path / ".update_weekly.lock"
    lock.mkdir()
    morto = subprocess.Popen(["true"])
    morto.wait()
    (lock / "pid").write_text(str(morto.pid))
    carimbo(tmp_path, "2026-09-28 13:48")
    r = run(tmp_path, "--se-vencido", agora="2026-09-28 17:48")
    assert r.returncode == 0
    assert "Lock órfão" in r.stdout and "Nada a fazer" in r.stdout
    assert not lock.exists()


def test_sem_rede_nao_conta_tentativa(tmp_path):
    r = run(tmp_path, "--se-vencido", agora="2026-09-29 10:00",
            URL_REDE="http://127.0.0.1:9/", ESPERA_REDE_SEG=0)
    assert r.returncode == 1
    assert "inacessível" in r.stdout
    assert not (tmp_path / ".tentativas").exists()
    assert not list(tmp_path.glob("update_*.log"))
    assert not (tmp_path / ".update_weekly.lock").exists()


def test_flag_desconhecida(tmp_path):
    assert run(tmp_path, "--xyz", agora="2026-09-29 10:00").returncode == 2
