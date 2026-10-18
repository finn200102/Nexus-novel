import {beforeEach,describe,expect,it,vi} from 'vitest';
import {authService} from './authService';
import apiClient from './apiClient';
import {activateAccountStorage} from './accountStorage';
import {hasPendingPrivateGuideIntents,loadPrivateGuideIntent,savePrivateGuideIntent} from './privateGuideService';
vi.mock('./apiClient',()=>({default:{post:vi.fn().mockResolvedValue({data:{}})},setSession:vi.fn(),refreshSession:vi.fn()}));
vi.mock('./progressSyncQueue',()=>({getQueuedProgress:()=>[]}));
vi.mock('./readerPreferenceSync',()=>({preferenceSyncStatus:()=>({pending:false})}));
beforeEach(()=>{vi.clearAllMocks();localStorage.clear();activateAccountStorage(1);});
const intent={action:'cancel' as const,id:4,body:{expected_revision:1,operation_id:'pending-confirmation'}};
describe('pending private companion logout handling',()=>{
 it('warns before logout and preserves an unresolved action when the reader stays signed in',async()=>{savePrivateGuideIntent(42,intent);const confirm=vi.spyOn(window,'confirm').mockReturnValue(false);await authService.logout();expect(confirm).toHaveBeenCalledWith(expect.stringContaining('companion actions'));expect(apiClient.post).not.toHaveBeenCalled();expect(loadPrivateGuideIntent(42)).toEqual(intent);confirm.mockRestore();});
 it('clears only the account-local pending acknowledgement after confirmed logout without canceling server work',async()=>{savePrivateGuideIntent(42,intent);const confirm=vi.spyOn(window,'confirm').mockReturnValue(true);await authService.logout();expect(apiClient.post).toHaveBeenCalledExactlyOnceWith('/auth/logout');activateAccountStorage(1);expect(hasPendingPrivateGuideIntents()).toBe(false);confirm.mockRestore();});
 it('does not show another account’s pending operation to the next reader',async()=>{savePrivateGuideIntent(42,intent);activateAccountStorage(2);expect(hasPendingPrivateGuideIntents()).toBe(false);const confirm=vi.spyOn(window,'confirm').mockReturnValue(true);await authService.logout();expect(confirm).not.toHaveBeenCalled();activateAccountStorage(1);expect(loadPrivateGuideIntent(42)).toEqual(intent);confirm.mockRestore();});
});
import {loadManifestIntent,saveManifestIntent,hasPendingManifestIntents} from './chapterManifestService';
it('warns for a lost chapter-change acknowledgement and clears it only after confirmed account logout',async()=>{
 const pending={action:'apply' as const,review_id:12,body:{review_token:'reviewed-changes',operation_id:'keep-same-operation'}};saveManifestIntent(42,pending);
 const confirm=vi.spyOn(window,'confirm').mockReturnValue(false);await authService.logout();expect(confirm).toHaveBeenCalledWith(expect.stringContaining('chapter changes'));expect(apiClient.post).not.toHaveBeenCalled();expect(loadManifestIntent(42)).toEqual(pending);
 activateAccountStorage(2);expect(hasPendingManifestIntents()).toBe(false);activateAccountStorage(1);expect(loadManifestIntent(42)).toEqual(pending);
 confirm.mockReturnValue(true);await authService.logout();expect(apiClient.post).toHaveBeenCalledExactlyOnceWith('/auth/logout');activateAccountStorage(1);expect(hasPendingManifestIntents()).toBe(false);confirm.mockRestore();
});
