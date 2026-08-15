KiraSOP anti-aggro scenarios v16

Новые config-параметры (по умолчанию оба True):

THREAT_SCENARIO_KILL_ENABLED = True
THREAT_SCENARIO_FULL_HP_ENABLED = True

THREAT_SCENARIO_KILL_ENABLED:
- post-death watcher после смерти текущей цели;
- no-target anti-aggro, когда валидной HP-полоски цели нет и персонаж получает урон;
- SWEEP остаётся приоритетнее retarget.

THREAT_SCENARIO_FULL_HP_ENABLED:
- live anti-aggro при живой FULL-HP цели и входящем уроне;
- повторная проверка ENGAGED anti-aggro цели, если она остаётся FULL HP.

Кнопки оверлея:
- Антиагр кил ON/OFF
- Антиагр фул хп ON/OFF

Кнопки сохраняют значения непосредственно в активный config_lu4.py/config_mw.py.
Если параметров ещё нет, оверлей автоматически добавит их с True при первом запуске.
Панель «Конфиг» также показывает оба параметра в разделе «Антиагр» с tooltip.

Комбинации:
- ON / ON: оба сценария;
- ON / OFF: только post-death/no-target;
- OFF / ON: только FULL-HP target;
- OFF / OFF: anti-aggro полностью выключен, HP-monitor не инициирует retarget.
