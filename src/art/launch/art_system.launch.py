"""실물 서버는 기본적으로 거절 전용. Fake는 테스트 명령으로만 별도 실행합니다."""
from launch import LaunchDescription
from launch_ros.actions import Node
def generate_launch_description():
    return LaunchDescription([
        Node(package='art',executable='artwork_pipeline',output='screen'),
        Node(package='art',executable='bridge',output='screen'),
        Node(package='art',executable='job_manager',output='screen'),
        Node(package='art',executable='drawing_controller',output='screen'),
        Node(package='art',executable='kiosk',output='screen'),
    ])
