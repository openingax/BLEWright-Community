#import <Foundation/Foundation.h>
/// Install once, before constructing CBCentralManager. Returns NO outside Simulator Debug.
/// Linking with -ObjC also installs automatically when BLEWRIGHT_ENABLE=1 is set.
FOUNDATION_EXPORT BOOL BWSimulatorBLEInstall(void);

/// Whether the Simulator Debug hook has been installed in this process.
FOUNDATION_EXPORT BOOL BWSimulatorBLEIsInstalled(void);

@class CBCentralManager;
/// Configure new central instances only. Existing sessions retain their endpoint.
/// Main-thread integration API; no effect outside Simulator Debug.
FOUNDATION_EXPORT void BWSimulatorBLESetPort(uint16_t port);
/// Finish server-side scan/connection cleanup before switching modes. Main queue callback.
FOUNDATION_EXPORT void BWSimulatorBLEEndSession(CBCentralManager *manager, void (^completion)(NSError *error));
