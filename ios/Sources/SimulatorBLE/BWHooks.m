#import "include/SimulatorBLE.h"
#import <TargetConditionals.h>
#if TARGET_OS_SIMULATOR && DEBUG
#import "BWCentral.h"
#import <objc/runtime.h>
static BOOL BWInstalled = NO;
BOOL BWSimulatorBLEIsInstalled(void) { return BWInstalled; }
static const void *BWContextKey = &BWContextKey;
static BWCentral *BWContext(id manager) { return objc_getAssociatedObject(manager, BWContextKey); }
void BWSimulatorBLEEndSession(CBCentralManager *manager, void (^completion)(NSError *)) {
    BWCentral *context = BWContext(manager);
    if (!context) { dispatch_async(dispatch_get_main_queue(), ^{ completion(nil); }); return; }
    context.delegate = nil;
    [context.rpc endSession:^(NSError *error) {
        // Keep the manager/context alive until the cleanup acknowledgement arrives.
        objc_setAssociatedObject(manager, BWContextKey, nil, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
        completion(error);
    }];
}
static void BWAttach(CBCentralManager *m, id delegate, dispatch_queue_t q) {
    BWCentral *c = BWContext(m);
    if (!c) {
        c = [[BWCentral alloc] initWithManager:m delegate:delegate queue:q];
        objc_setAssociatedObject(m, BWContextKey, c, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
    } else if (delegate)
        c.delegate = delegate;
}
@interface CBCentralManager (BWInit)
- (instancetype)initBWDelegate:(id)d queue:(dispatch_queue_t)q options:(NSDictionary *)options;
- (instancetype)initBWDelegate:(id)d queue:(dispatch_queue_t)q;
- (instancetype)initBWPlain;
@end
@implementation CBCentralManager (BWInit)
- (instancetype)initBWDelegate:(id)d queue:(dispatch_queue_t)q options:(NSDictionary *)options {
    if ((self = [self initBWDelegate:nil queue:q options:options]))
        BWAttach(self, d, q);
    return self;
}
- (instancetype)initBWDelegate:(id)d queue:(dispatch_queue_t)q {
    if ((self = [self initBWDelegate:nil queue:q]))
        BWAttach(self, d, q);
    return self;
}
- (instancetype)initBWPlain {
    if ((self = [self initBWPlain]))
        BWAttach(self, nil, nil);
    return self;
}
@end
static void BWReplace(Class c, SEL selector, id block) {
    Method method = class_getInstanceMethod(c, selector);
    NSCAssert(method, @"Missing CoreBluetooth selector %@", NSStringFromSelector(selector));
    class_replaceMethod(c, selector, imp_implementationWithBlock(block),
                        method_getTypeEncoding(method));
}
// Materialize inherited initializers on CBCentralManager before exchanging them;
// never alter the superclass implementation as a side effect.
static void BWExchange(Class c, SEL original, SEL replacement) {
    Method m = class_getInstanceMethod(c, original);
    class_addMethod(c, original, method_getImplementation(m), method_getTypeEncoding(m));
    method_exchangeImplementations(class_getInstanceMethod(c, original),
                                   class_getInstanceMethod(c, replacement));
}
BOOL BWSimulatorBLEInstall(void) {
    static dispatch_once_t once;
    dispatch_once(&once, ^{
      Class c = CBCentralManager.class;
      BWExchange(c, @selector(initWithDelegate:queue:options:),
                 @selector(initBWDelegate:queue:options:));
      BWExchange(c, @selector(initWithDelegate:queue:), @selector(initBWDelegate:queue:));
      BWExchange(c, @selector(init), @selector(initBWPlain));
      BWReplace(c, @selector(state), ^CBManagerState(id m) {
        BWCentral *s = BWContext(m);
        return s ? s.state : CBManagerStateUnknown;
      });
      BWReplace(c, @selector(delegate), ^id(id m) {
        return BWContext(m).delegate;
      });
      BWReplace(c, @selector(setDelegate:), ^(id m, id d) {
        BWContext(m).delegate = d;
      });
      BWReplace(c, @selector(isScanning), ^BOOL(id m) {
        return BWContext(m).scanning;
      });
      BWReplace(c, @selector(scanForPeripheralsWithServices:options:),
                ^(id m, NSArray *s, NSDictionary *o) {
                  [BWContext(m) scan:s options:o];
                });
      BWReplace(c, @selector(stopScan), ^(id m) {
        [BWContext(m) stopScan];
      });
      BWReplace(c, @selector(connectPeripheral:options:),
                ^(id m, CBPeripheral *p, NSDictionary *o) {
                  [BWContext(m) connect:(BWPeripheral *)p];
                });
      BWReplace(c, @selector(cancelPeripheralConnection:), ^(id m, CBPeripheral *p) {
        [BWContext(m) cancel:(BWPeripheral *)p];
      });
      BWReplace(c, @selector(retrievePeripheralsWithIdentifiers:), ^NSArray *(id m, NSArray *ids) {
        return [BWContext(m) retrieve:ids];
      });
      // This is a virtual Simulator permission, never a real-device authorization grant.
      BWReplace(CBManager.class, @selector(authorization), ^CBManagerAuthorization(id m) {
        return CBManagerAuthorizationAllowedAlways;
      });
      BWReplace(object_getClass(CBManager.class), @selector(authorization),
                ^CBManagerAuthorization(id m) {
                  return CBManagerAuthorizationAllowedAlways;
                });
      BWInstalled = YES;
      NSLog(@"SimulatorBLE installed — Simulator Debug only, RPC backend");
    });
    return YES;
}
@interface BWAutoInstall : NSObject
@end
@implementation BWAutoInstall
+ (void)load {
    if ([NSProcessInfo.processInfo.environment[@"BLEWRIGHT_ENABLE"] isEqual:@"1"])
        BWSimulatorBLEInstall();
}
@end
#else
void BWSimulatorBLESetPort(uint16_t port) {}
void BWSimulatorBLEEndSession(CBCentralManager *manager, void (^completion)(NSError *)) { completion(nil); }
BOOL BWSimulatorBLEIsInstalled(void) { return NO; }
BOOL BWSimulatorBLEInstall(void) { return NO; }
#endif
