import RPi.GPIO as GPIO
import time
from datetime import datetime
import adafruit_dht
import board
import requests
import spidev
import math
import logging
from config import SERVER_URL
from db_manager import execute_query
import sqlite3

conn = sqlite3.connect("farm.db",check_same_thread=False)
conn.execute("PRAGMA journal_mode=WAL")
cursor = conn.cursor()

# init Setting ##~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

# init logging
logging.basicConfig(level=logging.INFO)

#Pins
#devices
PINS = {'led': 5, 'fan':23, 'cooler': 24, 'water' : 13, 'heater' : 26}
#sensors
SENSORS = {'th':4, "soil":1,"co2":0}

# Low-Active devices list (ON in 0)
LOW_ACTIVE = ['led', 'water', 'heater']

#DHT11       
dht_device = adafruit_dht.DHT11(board.D4)


#SPI setting
spi = spidev.SpiDev()
spi.open(0,0)
spi.max_speed_hz = 1000000

#CO2 value setting
R1 = 23500
R2 = 10000
cal_A = 1.703
cal_B = 0.2677

#LED value setting
led_on_hour = 6
led_off_hour = 22

#Attributes
first = True
changed = False
update_data = []
alarm_text = {'led':'None','fan':'None','cooler':'None','water':'None','heater':'None'}



def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    for name, pin in PINS.items():
        initial = GPIO.HIGH if name in LOW_ACTIVE else GPIO.LOW
        GPIO.setup(pin, GPIO.OUT, initial=initial)
        
    for name, pin in SENSORS.items():
        GPIO.setup(pin, GPIO.IN)
        
def sync_device_state(device_name, target_on, alarm_msg=None):
    """
    integrate sync all of the devices' GPIO OUTPUT & DB STATE
    :param device_name : name of device(str)
    :param target_on : if ON/OFF(bool/int, 1=On, 0=Off)
    :param alarm_msg: if changed, write alarm message
    """
    pin = PINS[device_name]
    is_low_active = device_name in LOW_ACTIVE
    
    # Caculate GPIO OUTPUT
    # if (target_on is 1(True) && Low-Active) GPIO.LOW else GPIO.HIGH 
    output_level = GPIO.LOW if (target_on and is_low_active) else \
            GPIO.HIGH if (not target_on and is_low_active) else \
            GPIO.HIGH if target_on else GPIO.LOW
            
    GPIO.output(pin, output_level)
    
    # Update DB & Set Alarm
    execute_query(
        f"UPDATE device_status SET {device_name} = ? WHERE id = 0",
        (int(target_on),), commit=True
    )
    
    if alarm_msg:
        logging.info(f"[{device_name.uppder()}] {alarm_msg}")
        
        
def check_auto_logic(sensor_val, min_val, max_val, device_name, on_msg, off_msg):
    if sensor_val > max_val:
        sync_device_state(device_name, 1, on_msg)
    elif sensor_val < min_val:
        sync_device_state(device_name, 0, off_msg)
        

        


# Server URL #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
url = 'https://port-0-server-m7tucm4sab201860.sel4.cloudtype.app/sensors'
burl = 'https://port-0-server-m7tucm4sab201860.sel4.cloudtype.app'

# test_h/w_num #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
user_id = 'user@gmail.com'
#farm_id = 34


# Sensor Data #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

#Analog-Digital Convert
def read_adc(channel):
    if channel < 0 or channel > 7:
        return -1
    adc = spi.xfer2([1, (8+channel) << 4, 0])
    data = ((adc[1] & 3) << 8) + adc[2]
    return data

#CO2 init emf
def measure_emf_ini(channel):
    print("초기 EMF 측정 중 (3초 대기)...")
    time.sleep(3)
    emf_values = []
    for _ in range(30):  # 약 6초 동안 측정
        adc_val = read_adc(channel)
        v_out = (adc_val * 3.3) / 1023
        emf = v_out * ((R1 + R2) / R2)
        emf_values.append(emf)
        time.sleep(0.2)
    emf_ini = sum(emf_values) / len(emf_values)
    print(f"[EMF_ini] 초기 기준 전압: {emf_ini:.3f} V")
    return emf_ini


#WATER TIME
def calculate_watering_time(current_moisture, target_moisture, soil_volume_ml=24000, pump_flow_ml_per_sec=33.3):
    if current_moisture >= target_moisture:
        return 0

    required_water_ml = (soil_volume_ml * target_moisture - current_moisture) / 100
    watering_time_sec = required_water_ml / pump_flow_ml_per_sec
    return round(watering_time_sec, 2)

#WATER PERCENT
def get_moisture_percent(adc_value, dry_value=1022, wet_value=935):
    adc_value = max(min(adc_value, dry_value), wet_value)
    percent = (dry_value - adc_value) * 100 / (dry_value - wet_value)
    return round(percent, 1)

#CO2 PERCENT
def get_co2_ppm(adc_value, emf_ini):
    v_out = (adc_value * 3.3) / 1023
    emf = v_out * ((R1 + R2) / R2)

    ratio = emf / emf_ini
    if ratio <= 0:
        return 0

    co2_ppm = math.pow(10, (cal_A - ratio) / cal_B)
    return round(co2_ppm)



# Control #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

def ctrl_devices(temperature, humidity, soil_moisture, co2):
    # 모든 장치의 자동 설정값 한 번에 가져오기
    devices = ['led','fan','cooler','water','heater']
    configs={}
    for d in devices:
        res = execute_query("SELECT status, mode, duration, c_time FROM auto_ctrl WHERE device = ?", (d,))
        configs[d] = res[0]
        
    # 임계값(Options) 가져오기
    opt = execute_query("SELECT * FROM sensor_opt WHERE id = 0")[0]
    # opt[1] = tmin, [2]=tmax, [3]=hmin, [4]=hmax, [5]=smin, [6]=smax, [7]=cmin, [8]=cmax
    
    # 자동 제어 로직 통합 실행
    # FAN 제어(온도, 습도, CO2 복합 조건)
    if configs['fan'][1] == 1: #Auto 모드일 때만
        fan_trigger = (temperature > opt[2] or humidity > opt[4] or co2 > opt[8])
        sync_device_state('fan', 1 if fan_trigger else 0, "환경 부적합으로 팬 가동" if fan_trigger else "환경 안정화")
    
    # HEATER 제어
    if configs['heater'][1] == 1:
        heat_trigger = (temperature < opt[1])
        sync_device_state('heater', 1 if heat_trigger else 0, "온도 낮음: 히터 가동" if heat_trigger else "온도 정상")

    # WATER 제어 (기존 time.sleep(8)은 시스템을 멈추므로 주의!)
    if configs['water'][1] == 1:
        if soil_moisture < opt[5]:
             sync_device_state('water', 1, "토양 건조: 급수 시작")
             # 여기서 길게 멈추지 말고, 별도 스레드나 펌프 가동 로직만 태우는 것이 좋습니다.
        elif soil_moisture > opt[6]:
             sync_device_state('water', 0, "토양 수분 충분: 급수 중단")

    # 4. 수동 모드 시간 초과 체크 (Duration 체크)
    for d in devices:
        if configs[d][1] == 0: # Manual 모드라면
            ctime = datetime.strptime(configs[d][3], "%Y-%m-%d %H:%M:%S.%f")
            if (datetime.now() - ctime).seconds >= configs[d][2]:
                execute_query("UPDATE auto_ctrl SET mode = 1, duration = 0 WHERE device = ?", (d,), commit=True)
                logging.info(f"{d} 수동 모드 종료 -> 자동 모드 전환")
    

# Test #~~~~~~~~~~~~~~~~~~~~~~~
#start_time = time.time()

emf_ini = measure_emf_ini(0)
   
def sync_device(name, target_on, message=None):
    """GPIO 출력과 DB 상태를 한 번에 동기화"""
    pin = PINS[name]
    # 실제 출력 레벨 결정
    is_on = bool(target_on)
    level = (not is_on) if name in LOW_ACTIVE else is_on
    GPIO.output(pin, level)
    
    # DB 업데이트
    execute_query(f"UPDATE device_status SET {name} = ? WHERE id = 0", (int(is_on),), commit=True)
    
    if message:
        logging.info(f"[{name.upper()}] {message} (Status: {is_on})")
        # 클라우드 서버에 상태 변경 알림 전송 (선택 사항)
        try:
            requests.post(f"{SERVER_URL}/devices/{name}/status", json={"status": int(is_on), "content": message}, timeout=5)
        except: pass

def process_auto_control(sensors, opts, configs):
    """각 장치별 자동 제어 조건 판단"""
    temp, humi, soil, co2 = sensors
    # opt 구조 : [id, tmin, tmax, hmin, hmax, smin, smax, cmin, cmax]
    
    # FAN & COOLER (온도/습도/co2 복합)
    if configs['fan']['mode'] == 1:
        fan_on = temp > opts[2] or humi > opts[4] or co2 > opts[8]
        sync_device('fan', fan_on, "환경 부적합" if fan_on else "환경 안정")

    if configs['cooler']['mode'] == 1:
        cooler_on = temp > opts[2]
        sync_device('cooler', cooler_on, "고온 발생" if cooler_on else "온도 정상")
        
    # HEATER
    if configs['heater']['mode'] == 1:
        heater_on = temp < opts[1]
        sync_device('heater', heater_on, "저온 발생" if heater_on else "온도 정상")

    # 3. WATER (Non-blocking: 8초 대기 제거)
    if configs['water']['mode'] == 1:
        if soil < opts[5]: sync_device('water', 1, "토양 건조")
        elif soil > opts[6]: sync_device('water', 0, "수분 충분")

    # 4. LED (시간 기반)
    if configs['led']['mode'] == 1:
        is_day = 6 <= datetime.now().hour < 22
        sync_device('led', is_day, "주간 점등" if is_day else "야간 소등")
        
        
    
def check_manual_timeout(configs):
    """수동 모드 시간이 지나면 자동 모드로 복귀"""
    for name, cfg in configs.items():
        if cfg['mode'] == 0:
            try:
                ctime = datetime.strptime(cfg['c_time'], "%Y-%m-%d %H:%M:%S.%f")
                if (datetime.now() - ctime).seconds >= cfg['duration']:
                    execute_query("UPDATE auto_ctrl SET mode = 1, duration = 0 WHERE device = ?", (name,), commit=True)
                    logging.info(f"[{name}] 수동 시간 종료 -> 자동 전환")
            except: pass


def main():
    setup_gpio()
    emf_ini = measure_emf_ini(0)
    #emf_ini = 3.8
    
    while True:
        try:
            # 농장 활성화 상태 체크
            farm_res = execute_query("SELECT farm_id FROM farm_info WHERE id ='0'")
            if not farm_res or farm_res[0][0] ==0:
                time.sleep(5)
                continue
            
            # 센서 데이터 수집
            temp = dht_device.temperature
            humi = dht_device.humidity
            soil = get_moisture_percent(read_adc(1))
            co2 = get_co2_ppm(read_adc(0), emf_ini)
            
            if temp is None or humi is None: continue
            
            # 설정 및 모드 로드
            opts = execute_query("SELECT * FROM sensor_opt WHERE id = 0")[0]
            configs = {}
            for d in PINS.keys():
                c = execute_query("SELECT status, mode, duration, c_time FROM auto_ctrl WHERE device = ?", (d,))[0]
                configs[d] = {'status':c[0], 'mode':c[1], 'duration':c[2], 'c_time':c[3]}
                
            # 제어 실행
            process_auto_control((temp, humi, soil, co2), opts, configs)
            check_manual_timeout(configs)
            
            # 서버 데이터 전송
            payload = {"farm_id": farm_res[0][0], "temperature": temp, "humidity": humi, "soil_moisture": soil, "co2":co2}
            requests.post(f"{SERVER_URL}/sensors", json=payload, timeout=5)
            
            logging.info(f"Data Sent: T:{temp} H:{humi} S:{soil} C:{co2}")
            time.sleep(10) #10초 간격 루프
            
        except Exception as e:
            logging.error(f"Loop Error:{e}")
            time.sleep(5)

if __name__ == "__main__":
    try:
        main()
    finally:
        GPIO.cleanup()