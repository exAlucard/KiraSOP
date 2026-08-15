KiraSOP anti-aggro v7
=====================

Что исправлено по логу 2026-08-10 17:18-17:19
------------------------------------------------
В v6 post-death watcher закончил работу в 17:18:53 с WATCH_TIMEOUT_NO_THREAT.
После этого валидной цели не было, бот продолжал NEXT_TARGET, но HP персонажа
больше не измерялся вообще. Поэтому любой урон после timeout был невидим для
anti-aggro.

v7 добавляет постоянный IDLE/no-target монитор HP.

Алгоритм без таргета
--------------------
1. Пока anti_agr включен и нет активного watcher/anti-aggro, HP персонажа
   измеряется примерно каждые 0.35 сек даже при отсутствии цели.
2. Если HP упал минимум на порог (для LU4 default 4 абсолютных HP), событие
   NO_TARGET_HP_DROP_DETECTED запускает schedule_no_target_antiaggro.
3. Фаза сразу становится ACQUIRING — обычный NEXT_TARGET блокируется.
4. Делается короткое подтверждение ещё одним HP sample (default 2 samples
   вместе с первым, timeout 0.65 сек).
5. При подтверждении:
      NO_TARGET_THREAT_CONFIRMED
      ACQUIRE_COMMAND command='NEAREST_TARGET'
      ACQUIRE_SUCCESS
      ANTIAGGRO_ATTACK_COMMAND
6. Если игра сама успела выбрать агрессора, existing target принимается без
   лишнего NEAREST_TARGET.
7. Если подтверждение не прошло, возвращаемся в IDLE и постоянный монитор
   продолжает работу.

Новые события лога
------------------
NO_TARGET_HP_SAMPLE
NO_TARGET_MONITOR_HEARTBEAT
NO_TARGET_HP_DROP_DETECTED
NO_TARGET_INTERCEPT_SCHEDULE_RESULT
NO_TARGET_THREAT_SCHEDULED
NO_TARGET_THREAT_CONFIRM_SAMPLE
NO_TARGET_THREAT_CONFIRMED
NO_TARGET_THREAT_NOT_CONFIRMED
NO_TARGET_THREAT_END

Необязательные параметры config
-------------------------------
THREAT_NO_TARGET_DROP_THRESHOLD_ABS = 4.0
THREAT_NO_TARGET_MIN_OCR_CONFIDENCE = 70.0
THREAT_NO_TARGET_BASELINE_MAX_AGE = 1.5
THREAT_NO_TARGET_CONFIRM_SAMPLES = 2
THREAT_NO_TARGET_CONFIRM_INTERVAL = 0.12
THREAT_NO_TARGET_CONFIRM_TIMEOUT = 0.65
THREAT_NO_TARGET_CONFIRM_TOLERANCE_ABS = 2.0

Все параметры имеют defaults; конфиг менять не обязательно.

Важно
-----
2-секундная PENDING-логика для живой FULL-HP цели из v6 сохранена без
изменений. v7 добавляет отдельный путь только для ситуации, когда валидной
цели уже нет.
