#import "BWCentral.h"
#if TARGET_OS_SIMULATOR && DEBUG
#import <CommonCrypto/CommonDigest.h>
#import <objc/message.h>
// Runtime initialization/projection approach informed by ImpossiBLE (MIT), see ios/NOTICE.md.
static id BWRuntimeInit(id object, Class superclass) {
    struct objc_super s = {object, superclass};
    return ((id (*)(struct objc_super *, SEL))objc_msgSendSuper)(&s, @selector(init));
}
static void *BWDelegateObservation = &BWDelegateObservation;
@implementation BWPeripheral
- (instancetype)initBWWithAddress:(NSString *)address name:(NSString *)name {
    self = BWRuntimeInit(self, CBPeripheral.class);
    if (self) {
        _address = [address copy];
        _bwName = [name copy];
        unsigned char digest[CC_SHA256_DIGEST_LENGTH];
        NSData *d = [[@"BLEWright:" stringByAppendingString:address]
            dataUsingEncoding:NSUTF8StringEncoding];
        CC_SHA256(d.bytes, (CC_LONG)d.length, digest);
        _bwIdentifier = [[NSUUID alloc] initWithUUIDBytes:digest];
        _operations = [NSMutableArray array];
        _characteristics = [NSMutableDictionary dictionary];
        _allServices = [NSMutableArray array];
        _bwState = CBPeripheralStateDisconnected;
        _bwCanSend = YES;
        // iOS 27.1 CBPeripheral dealloc removes this self-observation. The public unavailable init
        // does not install it.
        [self addObserver:self forKeyPath:@"delegate" options:0 context:BWDelegateObservation];
    }
    return self;
}
- (void)observeValueForKeyPath:(NSString *)keyPath
                      ofObject:(id)object
                        change:(NSDictionary *)change
                       context:(void *)context {
    if (context == BWDelegateObservation)
        return;
    [super observeValueForKeyPath:keyPath ofObject:object change:change context:context];
}
- (NSUUID *)identifier {
    return _bwIdentifier;
}
- (NSString *)name {
    return self.bwName;
}
- (CBPeripheralState)state {
    return self.bwState;
}
- (id<CBPeripheralDelegate>)delegate {
    return self.bwDelegate;
}
- (void)setDelegate:(id<CBPeripheralDelegate>)delegate {
    self.bwDelegate = delegate;
}
- (NSArray *)services {
    return self.bwServices;
}
- (BOOL)canSendWriteWithoutResponse {
    return self.bwCanSend && self.state == CBPeripheralStateConnected;
}
- (NSUInteger)maximumWriteValueLengthForType:(CBCharacteristicWriteType)type {
    return MIN(MAX(self.attMTU, 23) - 3, 512);
}
- (void)discoverServices:(NSArray *)uuids {
    [_owner discover:self services:uuids];
}
- (void)discoverCharacteristics:(NSArray *)uuids forService:(CBService *)service {
    [_owner characteristics:self service:(BWService *)service filter:uuids];
}
- (void)discoverDescriptorsForCharacteristic:(CBCharacteristic *)c {
    [_owner descriptors:self characteristic:(BWCharacteristic *)c];
}
- (void)readValueForCharacteristic:(CBCharacteristic *)c {
    [_owner read:self characteristic:(BWCharacteristic *)c];
}
- (void)writeValue:(NSData *)data
    forCharacteristic:(CBCharacteristic *)c
                 type:(CBCharacteristicWriteType)type {
    [_owner write:self characteristic:(BWCharacteristic *)c data:data type:type];
}
- (void)setNotifyValue:(BOOL)enabled forCharacteristic:(CBCharacteristic *)c {
    [_owner notify:self characteristic:(BWCharacteristic *)c enabled:enabled];
}
- (void)readRSSI {
    [_owner readRSSI:self];
}
- (void)readValueForDescriptor:(CBDescriptor *)d {
    [_owner readDescriptor:self descriptor:(BWDescriptor *)d];
}
- (void)writeValue:(NSData *)data forDescriptor:(CBDescriptor *)d {
    [_owner writeDescriptor:self descriptor:(BWDescriptor *)d data:data];
}
- (void)discoverIncludedServices:(NSArray *)uuids forService:(CBService *)service {
    [NSException raise:NSInternalInconsistencyException
                format:@"SimulatorBLE: included services unsupported"];
}
- (void)openL2CAPChannel:(CBL2CAPPSM)psm {
    [NSException raise:NSInternalInconsistencyException format:@"SimulatorBLE: L2CAP unsupported"];
}
@end
@implementation BWService
- (instancetype)initBWWithDefinition:(NSDictionary *)d peripheral:(BWPeripheral *)p {
    self = BWRuntimeInit(self, CBService.class);
    if (self) {
        _remoteID = d[@"id"];
        _bwUUID = [CBUUID UUIDWithString:d[@"uuid"]];
        _bwPeripheral = p;
    }
    return self;
}
- (CBUUID *)UUID {
    return _bwUUID;
}
- (BOOL)isPrimary {
    return YES;
}
- (CBPeripheral *)peripheral {
    return _bwPeripheral;
}
- (NSArray *)characteristics {
    return self.bwCharacteristics;
}
- (NSArray *)includedServices {
    return nil;
}
@end
@implementation BWCharacteristic
- (instancetype)initBWWithDefinition:(NSDictionary *)d service:(BWService *)s {
    self = BWRuntimeInit(self, CBCharacteristic.class);
    if (self) {
        _remoteID = d[@"id"];
        _bwUUID = [CBUUID UUIDWithString:d[@"uuid"]];
        _bwService = s;
        _bwProperties = [d[@"properties"] unsignedIntegerValue];
    }
    return self;
}
- (CBUUID *)UUID {
    return _bwUUID;
}
- (CBService *)service {
    return _bwService;
}
- (CBCharacteristicProperties)properties {
    return _bwProperties;
}
- (NSData *)value {
    return self.bwValue;
}
- (BOOL)isNotifying {
    return self.bwNotifying;
}
- (NSArray *)descriptors {
    return self.bwDescriptors;
}
@end
@implementation BWDescriptor
- (instancetype)initBWWithDefinition:(NSDictionary *)d characteristic:(BWCharacteristic *)c {
    self = BWRuntimeInit(self, CBDescriptor.class);
    if (self) {
        _remoteID = d[@"id"];
        _bwUUID = [CBUUID UUIDWithString:d[@"uuid"]];
        _bwCharacteristic = c;
    }
    return self;
}
- (CBUUID *)UUID {
    return _bwUUID;
}
- (CBCharacteristic *)characteristic {
    return _bwCharacteristic;
}
- (id)value {
    return self.bwValue;
}
@end
#endif
