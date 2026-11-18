from setuptools import setup, find_packages
setup(name='art_artwork_pipeline', version='0.3.0', packages=find_packages(),
 data_files=[('share/ament_index/resource_index/packages',['resource/art_artwork_pipeline']),('share/art_artwork_pipeline',['package.xml','requirements-dl.txt','requirements-dl-lock.txt']),('share/art_artwork_pipeline/config',['config/motion_control.example.json'])],
 package_data={'art_artwork_pipeline':['static/*']}, install_requires=['setuptools'], zip_safe=False,
 maintainer='A4 Team',maintainer_email='maintainer@example.invalid',description='A4 art_artwork_pipeline',license='UNLICENSED',
 entry_points={'console_scripts':['configure_drawing = art_artwork_pipeline.motion_setup:main', 'inspect_drawing = art_artwork_pipeline.inspect_drawing:main', 'artwork_pipeline = art_artwork_pipeline.pipeline_node:main', 'lineart = art_artwork_pipeline.lineart.cli:main', 'plan_paths = art_artwork_pipeline.path_planner.cli:main']})
