Pod::Spec.new do |s|
  s.name = 'SimulatorBLE'
  s.version = '0.1.0'
  s.summary = 'Local Simulator-only CoreBluetooth adapter for BLEWright RPC'
  s.homepage = "https://github.com/openingax/BLEWright-Community"
  s.author = 'BLEWright'
  s.license = { :type => 'MIT', :file => '../LICENSE' }
  s.source = { :path => '.' }
  s.ios.deployment_target = '15.0'
  s.source_files = 'Sources/SimulatorBLE/**/*.{h,m}'
  s.public_header_files = 'Sources/SimulatorBLE/include/*.h'
  s.private_header_files = 'Sources/SimulatorBLE/*.h'
  s.requires_arc = true
  s.frameworks = 'CoreBluetooth', 'Network'
  s.pod_target_xcconfig = { 'GCC_PREPROCESSOR_DEFINITIONS[config=Debug]' => '$(inherited) DEBUG=1' }
end
