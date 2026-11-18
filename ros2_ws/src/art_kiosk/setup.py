from setuptools import setup, find_packages
setup(name='art_kiosk', version='0.3.0', packages=find_packages(),
 data_files=[('share/ament_index/resource_index/packages',['resource/art_kiosk']),('share/art_kiosk',['package.xml'])],
 package_data={'art_kiosk':['static/*']}, install_requires=['setuptools'], zip_safe=False,
 maintainer='A4 Team',maintainer_email='maintainer@example.invalid',description='A4 art_kiosk',license='UNLICENSED',
 entry_points={'console_scripts':['kiosk = art_kiosk.main:main']})
