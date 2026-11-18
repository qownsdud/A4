# 로컬 Fake 시험용 설정입니다. 실물 장비 실행 환경에서는 사용하지 않습니다.
# 기존 Discovery Server와 다른 PC의 노드로부터 시험 통신을 분리합니다.
unset ROS_DISCOVERY_SERVER ROS_SUPER_CLIENT ROS_STATIC_PEERS ROS_LOCALHOST_ONLY
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_DOMAIN_ID=97
