"""실물 프로필 미설정 시 실행을 거절합니다. Fake는 테스트 명령으로만 별도 실행합니다."""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('start_controller', default_value='true',
                              description='Controller 실행. 프로필 미설정 시 Goal 거절. Fake 시험 시 false로 지정'),
        Node(package='art_artwork_pipeline',executable='artwork_pipeline',output='screen'),
        Node(package='art_kiosk_bridge',executable='bridge',output='screen'),
        Node(package='art_job_manager',executable='job_manager',output='screen'),
        Node(package='art_drawing_controller',executable='drawing_controller',output='screen',
             condition=IfCondition(LaunchConfiguration('start_controller'))),
        Node(package='art_kiosk',executable='kiosk',output='screen'),
    ])
